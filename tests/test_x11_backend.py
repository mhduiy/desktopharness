"""Tests for the X11 desktop backend bundle and its composition root."""

import asyncio
import io
import os
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

from PIL import Image

from mcp_autogui.adapters.backends import x11_deepin
from mcp_autogui.adapters.compositor.x11 import X11CompositorAdapter
from mcp_autogui.core.models import (
    Action,
    ActionProposal,
    ActionType,
    ExecutionReceipt,
    ExecutionStatus,
    Point,
    PolicyDecision,
    PolicyStatus,
    ReasonCode,
    TaskState,
    TaskStatus,
    new_id,
    utc_now,
)
from mcp_autogui.core.store import ObjectStore
from mcp_autogui.desktop_backend import (
    DesktopTransactionResult,
    available_desktop_backends,
    create_desktop_backend,
    register_desktop_backend,
)
from mcp_autogui.server_config import load_server_config


from test_x11_compositor import X11FixtureRunner


CONFIG = pathlib.Path(__file__).parents[1] / "config"


class FakePyAutoGUI:
    """Records the pyautogui surface the shared executor and frame provider use.

    Injecting this is how the backend is tested without pyautogui installed:
    the backend's contract is "any module with the pyautogui surface".
    """

    def __init__(self, *, size=(1920, 1080), position=(912, 637), image=None):
        self._size = size
        self._position = position
        self._image = image or Image.new("RGB", (2, 3), (1, 2, 3))
        self.calls: list[tuple] = []

    # -- observation --------------------------------------------------------
    def size(self):
        self.calls.append(("size",))
        return self._size

    def position(self):
        self.calls.append(("position",))
        return self._position

    def screenshot(self):
        self.calls.append(("screenshot",))
        return self._image

    # -- input --------------------------------------------------------------
    def moveTo(self, x, y, duration=0):
        self.calls.append(("moveTo", (x, y), duration))

    def click(self, x, y, button="left", clicks=1, interval=0):
        self.calls.append(("click", (x, y), button, clicks, interval))

    def doubleClick(self, x, y, button="left"):
        self.calls.append(("doubleClick", (x, y), button))

    def mouseDown(self, button="left"):
        self.calls.append(("mouseDown", button))

    def mouseUp(self, button="left"):
        self.calls.append(("mouseUp", button))

    def dragTo(self, x, y, duration=1.2, button="left"):
        self.calls.append(("dragTo", (x, y), duration, button))

    def scroll(self, clicks):
        self.calls.append(("scroll", clicks))

    def hscroll(self, clicks):
        self.calls.append(("hscroll", clicks))

    def keyDown(self, key):
        self.calls.append(("keyDown", key))

    def keyUp(self, key):
        self.calls.append(("keyUp", key))

    def press(self, key, presses=1, interval=0):
        self.calls.append(("press", key, presses, interval))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def write(self, text, interval=0):
        self.calls.append(("write", text, interval))

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


class PyAutoGUILoaderTests(unittest.TestCase):
    def test_the_loader_forces_the_x11_session_and_script_friendly_defaults(self):
        fake = type("FakeModule", (), {"FAILSAFE": True, "PAUSE": 0.1})()
        environment = dict(os.environ)
        environment.pop("XDG_SESSION_TYPE", None)
        try:
            os.environ["XDG_SESSION_TYPE"] = "tty"  # what an SSH shell reports
            with patch.dict(sys.modules, {"pyautogui": fake}):
                module = x11_deepin.load_pyautogui()
            self.assertIs(module, fake)
            self.assertEqual(os.environ["XDG_SESSION_TYPE"], "x11")
            self.assertFalse(fake.FAILSAFE)
            self.assertEqual(fake.PAUSE, 0)
        finally:
            os.environ.clear()
            os.environ.update(environment)


class X11BackendBundleTests(unittest.TestCase):
    def setUp(self):
        self.store = ObjectStore()
        self.input_module = FakePyAutoGUI()
        self.backend = x11_deepin.create_backend(
            artifact_store=self.store,
            runner=X11FixtureRunner(),
            input_module=self.input_module,
        )

    def test_bundle_exposes_every_port_the_composition_root_needs(self):
        self.assertEqual(self.backend.backend_id, "x11-deepin")
        self.assertIsInstance(self.backend.compositor, X11CompositorAdapter)
        self.assertIs(self.backend.frame_provider._module, self.input_module)
        self.assertTrue(self.backend.policy_providers)
        self.assertTrue(callable(self.backend.create_tools))

    def test_observation_still_comes_from_ewmh_not_from_the_input_module(self):
        snapshot = self.backend.compositor.observe()
        self.assertEqual([item.window_id for item in snapshot.windows], [
            "0x4200007", "0x5a00014", "0x6a0000a", "0x2c00014",
        ])
        self.assertNotIn("size", self.input_module.names())

    def test_capture_observation_returns_png_bytes_and_the_active_window(self):
        payload, size, state = self.backend.capture_observation()
        self.assertEqual(size, (2, 3))
        self.assertEqual(Image.open(io.BytesIO(payload)).size, (2, 3))
        self.assertEqual(state["appId"], "deepin-terminal")
        self.assertIn("screenshot", self.input_module.names())

    def test_frame_provider_stores_the_screenshot_as_an_artifact(self):
        frame = self.backend.frame_provider.capture_frame()
        self.assertEqual(frame.pixel_size, (2, 3))
        self.assertEqual(frame.to_space, "desktop-logical")
        self.assertEqual(self.store.require(frame.image_ref)[:8], b"\x89PNG\r\n\x1a\n")

    def test_pointer_move_reaches_the_injected_module(self):
        receipt = self.backend.executor.execute(
            ActionProposal(
                proposal_id=new_id("proposal"),
                source="test",
                based_on_snapshot="snapshot-1",
                action=Action(ActionType.POINTER_MOVE, Point(700, 400), "desktop-logical"),
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.DELIVERED)
        self.assertIn(("moveTo", (700, 400), 0), self.input_module.calls)

    def test_a_click_is_mapped_and_delivered_through_the_module(self):
        receipt = self.backend.executor.execute(
            ActionProposal(
                proposal_id=new_id("proposal"),
                source="test",
                based_on_snapshot="snapshot-1",
                action=Action(ActionType.POINTER_CLICK, Point(384, 1060), "desktop-logical"),
            )
        )
        self.assertEqual(receipt.status, ExecutionStatus.DELIVERED)
        self.assertEqual(self.input_module.calls[-1], ("click", (384, 1060), "left", 1, 0))

    def test_the_backend_is_registered_for_config_selection(self):
        self.assertIn("x11-deepin", available_desktop_backends())
        selected = create_desktop_backend(
            "x11-deepin", artifact_store=ObjectStore(), input_module=FakePyAutoGUI()
        )
        self.assertEqual(selected.backend_id, x11_deepin.BACKEND_ID)

    def test_registering_a_backend_twice_is_rejected(self):
        with self.assertRaises(ValueError):
            register_desktop_backend(x11_deepin.BACKEND_ID, x11_deepin.create_backend)

    def test_the_shipped_config_selects_this_backend(self):
        config = load_server_config(str(CONFIG / "mcp-autoui-x11.json"))
        self.assertEqual(config.desktop_backend, "x11-deepin")
        self.assertEqual(config.effective_config()["transport"]["host"], "127.0.0.1")

    def test_the_treeland_config_still_loads(self):
        config = load_server_config(str(CONFIG / "mcp-autoui.json"))
        self.assertEqual(config.desktop_backend, "treeland-deepin")


class FakeTransactions:
    """Records the contracts the desktop tools build on the caller's behalf."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.contracts = []
        self.proposals = []

    async def execute(self, contract, proposal_builder):
        self.contracts.append(contract)
        proposal = proposal_builder(self.snapshot)
        self.proposals.append(proposal)
        return DesktopTransactionResult(
            snapshot=self.snapshot,
            proposal=proposal,
            decision=PolicyDecision(
                proposal_id=proposal.proposal_id,
                status=PolicyStatus.ALLOW,
                reason_code=ReasonCode.OK,
            ),
            receipt=ExecutionReceipt(
                new_id("execution"),
                proposal.proposal_id,
                ExecutionStatus.DELIVERED,
                proposal.action,
                utc_now(),
                utc_now(),
            ),
            state=TaskState(contract.task_id),
        )

    async def evaluate(self, task_id):
        return TaskState(task_id, status=TaskStatus.RUNNING)


CAPABILITY = {
    "capability_id": "desktop.workspace.2",
    "category": "workspace",
    "display_name": "Workspace 2",
    "enabled": True,
    "auto_invokable": True,
    "normalized_hotkeys": [["super", "2"]],
    "policy": "allow",
    "risk": "low",
}


class X11DesktopToolTests(unittest.TestCase):
    """The platform tools must route through the core transaction, not inject."""

    def setUp(self):
        self.store = ObjectStore()
        self.compositor = X11CompositorAdapter(runner=X11FixtureRunner(), artifact_store=self.store)
        self.snapshot = self.compositor.observe()
        self.transactions = FakeTransactions(self.snapshot)
        backend = x11_deepin.create_backend(
            artifact_store=self.store,
            runner=X11FixtureRunner(),
            input_module=FakePyAutoGUI(),
            capability_loader=lambda: [CAPABILITY],
            capability_resolver=lambda capability_id: CAPABILITY if capability_id == "desktop.workspace.2" else None,
        )
        self.tools = backend.create_tools(self.transactions, _run_blocking)

    def test_listing_capabilities_uses_the_platform_catalogue(self):
        self.assertEqual(
            [item["capability_id"] for item in self.tools.list_capabilities()],
            ["desktop.workspace.2"],
        )

    def test_invoking_a_shortcut_builds_its_own_narrow_contract(self):
        result = asyncio.run(self.tools.invoke_shortcut("desktop.workspace.2"))
        self.assertEqual(result["status"], "success")
        contract = self.transactions.contracts[0]
        self.assertEqual({item.value for item in contract.permissions.actions}, {"platform.invoke"})
        self.assertEqual(contract.permissions.semantic_intents, frozenset({"navigation"}))
        self.assertEqual(contract.limits.max_steps, 1)
        self.assertFalse(contract.explicit_user_authorization)

    def test_a_capability_outside_the_auto_invokable_set_is_refused(self):
        backend = x11_deepin.create_backend(
            artifact_store=self.store,
            runner=X11FixtureRunner(),
            input_module=FakePyAutoGUI(),
            capability_loader=lambda: [CAPABILITY],
            capability_resolver=lambda capability_id: {**CAPABILITY, "auto_invokable": False},
        )
        tools = backend.create_tools(self.transactions, _run_blocking)
        with self.assertRaises(PermissionError):
            asyncio.run(tools.invoke_shortcut("desktop.workspace.2"))
        self.assertEqual(self.transactions.contracts, [])

    def test_launching_an_application_routes_through_the_transaction(self):
        result = asyncio.run(
            self.tools.launch_application("deepin-terminal", expected_active_app_id="deepin-terminal")
        )
        self.assertEqual(result["status"], "success")
        contract = self.transactions.contracts[0]
        self.assertEqual({item.value for item in contract.permissions.actions}, {"application.launch"})
        self.assertEqual(self.transactions.proposals[0].action.parameters["app_id"], "deepin-terminal")
        self.assertEqual(result["task_validation"]["status"], "passed")


async def _run_blocking(function, *args, **kwargs):
    return function(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
