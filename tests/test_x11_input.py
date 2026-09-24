"""Tests for the xdotool input adapter and its receipts.

The command lines are asserted because they *are* the contract with an external
tool: a wrong button number or a missing ``--sync`` silently does the wrong
thing to the desktop instead of failing.
"""

import io
import subprocess
import unittest
from unittest.mock import patch

from mcp_autogui.adapters.executor.pyautogui import PyAutoGUIExecutor
from mcp_autogui.adapters.executor.xdotool_input import XdotoolInputModule
from mcp_autogui.core.models import (
    Action,
    ActionProposal,
    ActionType,
    ExecutionStatus,
    Point,
    ReasonCode,
    new_id,
)


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000002000000030802000000368849d6"
    "0000001449444154789c636464626660606062606040500000c4000c1eb7fda2"
    "0000000049454e44ae426082"
)


class XdotoolRecorder:
    """Records every xdotool invocation and answers the query subcommands."""

    def __init__(self, *, responses=None, returncode=0, stderr="boom"):
        self.commands: list[tuple[str, ...]] = []
        self.responses = dict(responses or {})
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, argv, *, c_locale: bool = False, timeout: float = 0.0):
        argv = [str(item) for item in argv]
        self.commands.append(tuple(argv))
        return subprocess.CompletedProcess(argv, self.returncode, self.responses.get(" ".join(argv), ""), self.stderr)

    @property
    def args(self) -> list[list[str]]:
        return [list(command[1:]) for command in self.commands]  # drop the "xdotool" head


def module(recorder=None, *, responses=None) -> tuple[XdotoolInputModule, XdotoolRecorder]:
    runner = recorder or XdotoolRecorder(
        responses=responses
        or {"xdotool getmouselocation --shell": "X=10\nY=20\nSCREEN=0\nWINDOW=1\n"}
    )
    return XdotoolInputModule(runner=runner), runner


class PointerCommandTests(unittest.TestCase):
    def test_move_is_synchronous_and_rounded(self):
        adapter, runner = module()
        adapter.moveTo(100.4, 200.6)
        self.assertEqual(runner.args, [["mousemove", "--sync", "100", "201"]])

    def test_click_presses_the_named_button_at_the_rounded_point(self):
        adapter, runner = module()
        adapter.click(5, 6, button="right")
        self.assertEqual(runner.args, [["mousemove", "--sync", "5", "6", "click", "3"]])

    def test_repeated_click_carries_repeat_and_delay(self):
        adapter, runner = module()
        adapter.doubleClick(1, 2, button="middle")
        adapter.click(3, 4, clicks=3, interval=0.25)
        self.assertEqual(
            runner.args,
            [
                ["mousemove", "--sync", "1", "2", "click", "--repeat", "2", "2"],
                ["mousemove", "--sync", "3", "4", "click", "--repeat", "3", "--delay", "250", "1"],
            ],
        )

    def test_press_and_release_are_separate_messages(self):
        adapter, runner = module()
        adapter.mouseDown("left")
        adapter.mouseUp("left")
        self.assertEqual(runner.args, [["mousedown", "1"], ["mouseup", "1"]])

    @patch("mcp_autogui.adapters.executor.xdotool_input.time.sleep")
    def test_drag_starts_at_the_current_pointer_and_ends_exactly_on_target(self, _sleep):
        adapter, runner = module(
            responses={"xdotool getmouselocation --shell": "X=0\nY=0\nSCREEN=0\nWINDOW=1\n"}
        )
        adapter.dragTo(100, 50)
        args = runner.args
        pressed = [item for item in args if item[0] in {"mousedown", "mouseup"}]
        self.assertEqual(pressed, [["mousedown", "1"], ["mouseup", "1"]])
        moves = [item for item in args if item[0] == "mousemove"]
        self.assertGreaterEqual(len(moves), 5)
        self.assertEqual(moves[-1][1:], ["--sync", "100", "50"])

    @patch("mcp_autogui.adapters.executor.xdotool_input.time.sleep")
    def test_a_longer_duration_produces_a_slower_drag(self, _sleep):
        adapter, runner = module(
            responses={"xdotool getmouselocation --shell": "X=0\nY=0\nSCREEN=0\nWINDOW=1\n"}
        )
        adapter.dragTo(1000, 0, duration=3.0)
        moves = [item for item in runner.args if item[0] == "mousemove"]
        self.assertEqual(len(moves), 60)  # capped at _DRAG_MAX_STEPS
        self.assertEqual(moves[-1][1:], ["--sync", "1000", "0"])

    @patch("mcp_autogui.adapters.executor.xdotool_input.time.sleep")
    def test_a_zero_duration_drag_still_presses_moves_and_releases(self, _sleep):
        adapter, runner = module(
            responses={"xdotool getmouselocation --shell": "X=5\nY=5\nSCREEN=0\nWINDOW=1\n"}
        )
        adapter.dragTo(15, 5, duration=0)
        commands = [item[0] for item in runner.args]
        self.assertEqual(commands[0], "getmouselocation")
        self.assertEqual(commands[1], "mousedown")
        self.assertEqual(commands[-1], "mouseup")
        self.assertIn("mousemove", commands)

    @patch("mcp_autogui.adapters.executor.xdotool_input.time.sleep")
    def test_drag_releases_the_button_even_if_a_move_fails(self, _sleep):
        runner = XdotoolRecorder(responses={"xdotool getmouselocation --shell": "X=0\nY=0\nSCREEN=0\nWINDOW=1\n"})
        adapter = XdotoolInputModule(runner=runner)
        original = adapter._xdotool

        def failing(args):
            if list(args)[:1] == ["mousemove"] and "-100" in args:
                raise RuntimeError("pointer refused")
            return original(args)

        adapter._xdotool = failing  # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            adapter.dragTo(-100, 0)
        self.assertEqual(runner.args[-1], ["mouseup", "1"])

    def test_scroll_direction_and_magnitude(self):
        adapter, runner = module()
        adapter.scroll(3)
        adapter.scroll(-2)
        adapter.scroll(0)
        adapter.hscroll(1)
        adapter.hscroll(-4)
        self.assertEqual(
            runner.args,
            [
                ["click", "--repeat", "3", "4"],
                ["click", "--repeat", "2", "5"],
                ["click", "7"],
                ["click", "--repeat", "4", "6"],
            ],
        )

    def test_unknown_button_is_rejected_before_touching_the_desktop(self):
        adapter, runner = module()
        with self.assertRaises(ValueError):
            adapter.click(1, 1, button="thumb")
        self.assertEqual(runner.commands, [])


class KeyboardCommandTests(unittest.TestCase):
    def test_named_keys_use_keysym_spelling(self):
        adapter, runner = module()
        adapter.keyDown("escape")
        adapter.press("f4")
        adapter.press("a", presses=2, interval=0.1)
        self.assertEqual(
            runner.args,
            [["keydown", "Escape"], ["key", "F4"], ["key", "--repeat", "2", "--delay", "100", "a"]],
        )

    def test_shortcuts_join_keys_with_a_plus(self):
        adapter, runner = module()
        adapter.hotkey("ctrl", "alt", "t")
        self.assertEqual(runner.args, [["key", "ctrl+alt+t"]])

    def test_typing_passes_utf8_text_after_a_separator(self):
        adapter, runner = module()
        adapter.write("密码 abc")
        self.assertEqual(runner.args, [["type", "--", "密码 abc"]])

    def test_failure_is_raised_not_swallowed(self):
        runner = XdotoolRecorder(returncode=1, stderr="Cannot open display")
        adapter = XdotoolInputModule(runner=runner)
        with self.assertRaises(RuntimeError):
            adapter.moveTo(1, 1)


class ObservationCommandTests(unittest.TestCase):
    def test_pointer_and_display_are_read_from_xdotool(self):
        adapter, _ = module(
            responses={
                "xdotool getmouselocation --shell": "X=931\nY=643\nSCREEN=0\nWINDOW=111149066\n",
                "xdotool getdisplaygeometry": "1920 1080\n",
            }
        )
        self.assertEqual(adapter.position(), (931, 643))
        self.assertEqual(adapter.size(), (1920, 1080))

    def test_screenshot_returns_a_decoded_image(self):
        class BinaryRecorder:
            def __init__(self):
                self.commands: list[tuple[str, ...]] = []

            def __call__(self, argv, *, timeout: float = 0.0):
                self.commands.append(tuple(argv))
                return PNG

        recorder = BinaryRecorder()
        adapter = XdotoolInputModule(binary_runner=recorder)
        image = adapter.screenshot()
        self.assertEqual(image.size, (2, 3))
        # -silent is required: import rings the X bell otherwise, which is an
        # audible beep on hosts whose X bell reaches the PC speaker.
        self.assertEqual(recorder.commands, [("import", "-silent", "-window", "root", "png:-")])


class ExecutorIntegrationTests(unittest.TestCase):
    """The reused executor must keep its receipt semantics over xdotool."""

    def build(self, recorder, **kwargs):
        adapter = XdotoolInputModule(runner=recorder)
        return PyAutoGUIExecutor(adapter, **kwargs)

    def proposal(self, action):
        return ActionProposal(
            proposal_id=new_id("proposal"),
            source="test",
            based_on_snapshot="snapshot-1",
            action=action,
        )

    def test_a_click_that_the_device_accepts_is_delivered(self):
        recorder = XdotoolRecorder()
        executor = self.build(recorder, coordinate_mapper=lambda point, space, proposal: point)
        receipt = executor.execute(
            self.proposal(Action(ActionType.POINTER_CLICK, Point(10, 20), "desktop-logical"))
        )
        self.assertEqual(receipt.status, ExecutionStatus.DELIVERED)
        self.assertEqual(receipt.executed_action.coordinate, Point(10, 20))
        self.assertEqual(recorder.args, [["mousemove", "--sync", "10", "20", "click", "1"]])

    def test_a_device_error_becomes_a_failed_receipt_with_a_reason_code(self):
        executor = self.build(XdotoolRecorder(returncode=1))
        receipt = executor.execute(
            self.proposal(Action(ActionType.POINTER_MOVE, Point(1, 2), "desktop-logical"))
        )
        self.assertEqual(receipt.status, ExecutionStatus.FAILED)
        self.assertEqual(receipt.error_code, ReasonCode.EXECUTOR_ACTION_FAILED)
        self.assertIsNone(receipt.executed_action)

    def test_an_unsupported_coordinate_space_is_refused_before_injection(self):
        from mcp_autogui.adapters.backends.x11_deepin import create_backend
        from mcp_autogui.core.store import ObjectStore

        # The xdotool module stays selectable as the alternative input stack.
        recorder = XdotoolRecorder()
        backend = create_backend(
            artifact_store=ObjectStore(),
            runner=recorder,
            input_module=XdotoolInputModule(runner=recorder, binary_runner=lambda argv, timeout=0.0: PNG),
        )
        receipt = backend.executor.execute(
            self.proposal(Action(ActionType.POINTER_MOVE, Point(1, 2), "screen-pixels"))
        )
        self.assertEqual(receipt.status, ExecutionStatus.FAILED)
        self.assertEqual(recorder.commands, [])

    def test_application_launch_is_delegated_to_the_backend_handler(self):
        seen = []

        def handler(proposal):
            seen.append(proposal.action)
            from mcp_autogui.core.models import ExecutionReceipt, utc_now

            now = utc_now()
            return ExecutionReceipt(
                new_id("execution"),
                proposal.proposal_id,
                ExecutionStatus.DELIVERED,
                proposal.action,
                now,
                now,
            )

        recorder = XdotoolRecorder()
        executor = self.build(recorder, application_handler=handler)
        receipt = executor.execute(
            self.proposal(Action(ActionType.APPLICATION_LAUNCH, parameters={"app_id": "deepin-terminal"}))
        )
        self.assertEqual(receipt.status, ExecutionStatus.DELIVERED)
        self.assertEqual(len(seen), 1)
        self.assertEqual(recorder.commands, [])


if __name__ == "__main__":
    unittest.main()
