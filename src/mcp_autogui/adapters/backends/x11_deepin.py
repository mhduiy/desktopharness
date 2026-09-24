"""X11/Deepin desktop bundle for the generic desktop harness.

The X11 family differs from the Treeland backend in three ways, all confined to
this package: EWMH is the observation source, ``xdotool`` injects input, and
ImageMagick captures frames.  Everything downstream of the ports — policy,
guards, receipts, evidence, assertions, task state and audit — is the shared
core and is not reimplemented here.

The application launcher and the desktop tool implementations are the same
Deepin/desktop-generic pieces the Treeland backend uses; they only receive
X11 observation callbacks.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from typing import Any

from ..compositor.x11 import COORDINATE_SPACE_ID, X11CompositorAdapter
from ..executor import PyAutoGUIExecutor
from ..frame import PyAutoGUIFrameProvider
from ..platform import DeepinKeybindingProvider
from ..x11_commands import Runner
from .treeland_deepin import DdeApplicationLauncher
from .treeland_deepin_tools import TreelandDeepinTools
from ...core.models import ActionProposal, Point
from ...core.store import ObjectStore
from ...desktop_backend import DesktopBackend, DesktopTransactionRunner, RunBlocking
from ...desktop_capabilities import (
    find_capability,
    load_desktop_application_catalogue,
    load_keybinding_catalogue,
    validate_application_id,
)


BACKEND_ID = "x11-deepin"


def load_pyautogui() -> Any:
    """Import the project's pyautogui stack configured for scripted control.

    pyautogui refuses to import unless ``XDG_SESSION_TYPE`` names a known
    session, and a service started over SSH inherits ``tty``; this backend only
    ever runs on X11, so the value is set before the import.  Its defaults are
    also hostile to automation: ``FAILSAFE`` aborts when the pointer reaches a
    screen corner, and ``PAUSE`` sleeps 100 ms inside every call.
    """
    os.environ["XDG_SESSION_TYPE"] = "x11"
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    return pyautogui


def create_backend(
    *,
    artifact_store: ObjectStore,
    runner: Runner | None = None,
    input_module: Any | None = None,
    capability_loader: Callable[[], list[dict[str, Any]]] | None = None,
    capability_resolver: Callable[[str], dict[str, Any] | None] | None = None,
) -> DesktopBackend:
    """Construct the complete X11/Deepin port bundle.

    Input injection defaults to the project's pyautogui stack — the same one the
    Treeland backend uses, which drives X11 through Xlib/XTest and Wayland
    through ydotool.  ``input_module`` overrides it (the dependency-free
    ``XdotoolInputModule`` is the documented alternative); either module only
    has to expose the pyautogui surface the shared executor already expects.
    """
    compositor_kwargs: dict[str, Any] = {"artifact_store": artifact_store}
    if runner is not None:
        compositor_kwargs["runner"] = runner
    compositor = X11CompositorAdapter(**compositor_kwargs)

    if input_module is None:
        input_module = load_pyautogui()
    application_launcher = DdeApplicationLauncher()
    capability_loader = capability_loader or load_keybinding_catalogue
    capability_resolver = capability_resolver or find_capability
    platform_provider = DeepinKeybindingProvider(
        loader=capability_loader, resolver=capability_resolver
    )

    def coordinate_mapper(
        point: Point, coordinate_space: str, proposal: ActionProposal
    ) -> Point:
        # X11 root pixels are the canonical desktop space: the observation's
        # coordinate space is the root window geometry, so no scaling happens
        # and multi-output layouts cannot drift.
        if coordinate_space != COORDINATE_SPACE_ID:
            raise ValueError("unsupported executor coordinate space")
        return point

    executor = PyAutoGUIExecutor(
        input_module,
        coordinate_mapper=coordinate_mapper,
        platform_resolver=platform_provider.resolve,
        application_handler=application_launcher.launch,
    )
    frame_provider = PyAutoGUIFrameProvider(input_module, artifact_store)
    capture_observation = lambda: _capture_observation(  # noqa: E731
        input_module, compositor.active_window_facts
    )

    def create_tools(
        transactions: DesktopTransactionRunner,
        run_blocking: RunBlocking,
    ) -> TreelandDeepinTools:
        return TreelandDeepinTools(
            transactions,
            artifact_store,
            run_blocking,
            capability_loader=capability_loader,
            capability_resolver=capability_resolver,
            application_loader=load_desktop_application_catalogue,
            application_validator=validate_application_id,
            application_result_for=application_launcher.result_for,
            read_observation_state=compositor.active_window_facts,
            capture_observation=capture_observation,
            active_window_summary=_active_window_summary,
        )

    return DesktopBackend(
        backend_id=BACKEND_ID,
        compositor=compositor,
        executor=executor,
        frame_provider=frame_provider,
        capture_observation=capture_observation,
        policy_providers=(platform_provider,),
        create_tools=create_tools,
    )


def _active_window_summary(state: object) -> dict[str, object] | None:
    """The tool layer expects the ``appId`` shape; the probe already returns it."""
    if not isinstance(state, dict):
        return None
    return {
        "appId": state.get("appId"),
        "title": state.get("title"),
        "window_id": state.get("window_id"),
    }


def _capture_observation(
    input_module: XdotoolInputModule,
    read_observation_state: Callable[[], dict[str, object] | None],
) -> tuple[bytes, tuple[int, int], object]:
    screenshot = input_module.screenshot().convert("RGB")
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    return buffer.getvalue(), screenshot.size, read_observation_state()
