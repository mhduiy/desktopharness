"""PyAutoGUI-shaped input surface backed by the ``xdotool`` CLI.

The existing ``PyAutoGUIExecutor`` and ``PyAutoGUIFrameProvider`` already own
the action dispatch, receipt semantics and frame bookkeeping; this module only
supplies the device calls they expect, so the X11 backend reuses both verbatim
instead of duplicating them.
"""

from __future__ import annotations

import io
import re
import time
from collections.abc import Sequence

from ..x11_commands import BinaryRunner, Runner, run_binary, run_command


_BUTTONS = {"left": 1, "middle": 2, "right": 3}
_SCROLL_UP = 4
_SCROLL_DOWN = 5
_SCROLL_LEFT = 6
_SCROLL_RIGHT = 7
_POSITION = re.compile(r"^X=(-?\d+)$", re.M)
_POSITION_Y = re.compile(r"^Y=(-?\d+)$", re.M)
# A drag always emits at least this many moves; a larger `duration` scales the
# count up (and paces them) so slow drags stay slow.
_DRAG_STEPS = 5
_DRAG_STEPS_PER_SECOND = 20
_DRAG_MAX_STEPS = 60


class XdotoolInputModule:
    """Minimal pyautogui-compatible module implemented with ``xdotool``."""

    def __init__(
        self,
        *,
        runner: Runner = run_command,
        binary_runner: BinaryRunner = run_binary,
        timeout: float = 10.0,
    ) -> None:
        self._run = runner
        self._run_binary = binary_runner
        self._timeout = timeout

    # -- transport ----------------------------------------------------------

    def _xdotool(self, args: Sequence[str]) -> str:
        completed = self._run(["xdotool", *args], timeout=self._timeout)
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            raise RuntimeError(
                f"xdotool {' '.join(args)} failed ({completed.returncode}): "
                f"{detail[-1] if detail else 'no stderr'}"
            )
        return completed.stdout or ""

    @staticmethod
    def _xy(x: float, y: float) -> list[str]:
        return ["--sync", str(int(round(x))), str(int(round(y)))]

    # -- pointer ------------------------------------------------------------

    def moveTo(self, x: float, y: float, duration: float = 0) -> None:
        # xdotool has no animated move; the pointer is placed synchronously and
        # `duration` is accepted for signature compatibility only.
        self._xdotool(["mousemove", *self._xy(x, y)])

    def position(self) -> tuple[int, int]:
        output = self._xdotool(["getmouselocation", "--shell"])
        x = _POSITION.search(output)
        y = _POSITION_Y.search(output)
        if not x or not y:
            raise RuntimeError("xdotool did not report the pointer position")
        return int(x.group(1)), int(y.group(1))

    def size(self) -> tuple[int, int]:
        parts = self._xdotool(["getdisplaygeometry"]).split()
        if len(parts) != 2:
            raise RuntimeError("xdotool did not report the display geometry")
        return int(parts[0]), int(parts[1])

    def mouseDown(self, button: str = "left") -> None:
        self._xdotool(["mousedown", str(_button(button))])

    def mouseUp(self, button: str = "left") -> None:
        self._xdotool(["mouseup", str(_button(button))])

    def click(
        self,
        x: float,
        y: float,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0,
    ) -> None:
        args = ["mousemove", *self._xy(x, y), "click"]
        if clicks > 1:
            args += ["--repeat", str(int(clicks))]
        if interval:
            args += ["--delay", str(int(round(float(interval) * 1000)))]
        args.append(str(_button(button)))
        self._xdotool(args)

    def doubleClick(self, x: float, y: float, button: str = "left") -> None:
        self.click(x, y, button=button, clicks=2)

    def dragTo(self, x: float, y: float, duration: float = 1.2, button: str = "left") -> None:
        """Press at the current pointer position and drag to ``(x, y)``.

        ``duration`` is honoured: a slow drag (large duration) emits many small
        intermediate moves, because window managers and apps that follow the
        pointer need motion events to keep up with a drag.
        """
        number = str(_button(button))
        start_x, start_y = self.position()
        seconds = max(0.0, float(duration))
        steps = _DRAG_STEPS
        if seconds > 0:
            steps = max(_DRAG_STEPS, min(_DRAG_MAX_STEPS, int(round(seconds * _DRAG_STEPS_PER_SECOND))))
        delay = seconds / steps if steps else 0.0
        self._xdotool(["mousedown", number])
        try:
            for step in range(1, steps + 1):
                ratio = step / steps
                self._xdotool(
                    [
                        "mousemove",
                        *self._xy(
                            start_x + (x - start_x) * ratio,
                            start_y + (y - start_y) * ratio,
                        ),
                    ]
                )
                if delay:
                    time.sleep(delay)
        finally:
            self._xdotool(["mouseup", number])

    def scroll(self, clicks: int) -> None:
        self._wheel(int(clicks), positive=_SCROLL_UP, negative=_SCROLL_DOWN)

    def hscroll(self, clicks: int) -> None:
        self._wheel(int(clicks), positive=_SCROLL_RIGHT, negative=_SCROLL_LEFT)

    def _wheel(self, clicks: int, *, positive: int, negative: int) -> None:
        if clicks == 0:
            return
        args = ["click"]
        if abs(clicks) > 1:
            args += ["--repeat", str(abs(clicks))]
        args.append(str(positive if clicks > 0 else negative))
        self._xdotool(args)

    # -- keyboard -----------------------------------------------------------

    def keyDown(self, key: str) -> None:
        self._xdotool(["keydown", _key(key)])

    def keyUp(self, key: str) -> None:
        self._xdotool(["keyup", _key(key)])

    def press(self, key: str, presses: int = 1, interval: float = 0) -> None:
        args = ["key"]
        if presses > 1:
            args += ["--repeat", str(int(presses))]
        if interval:
            args += ["--delay", str(int(round(float(interval) * 1000)))]
        args.append(_key(key))
        self._xdotool(args)

    def hotkey(self, *keys: str) -> None:
        self._xdotool(["key", "+".join(_key(item) for item in keys)])

    def write(self, text: str, interval: float = 0) -> None:
        args = ["type"]
        if interval:
            args += ["--delay", str(int(round(float(interval) * 1000)))]
        args += ["--", text]
        self._xdotool(args)

    # -- capture ------------------------------------------------------------

    def screenshot(self):
        """Return the root window as a PIL image (ImageMagick ``import``).

        ``-silent`` matters: ``import`` rings the X bell by default, and on
        machines where the X bell is routed to the PC speaker that is an
        audible beep on every single frame.
        """
        from PIL import Image

        payload = self._run_binary(
            ["import", "-silent", "-window", "root", "png:-"], timeout=self._timeout
        )
        return Image.open(io.BytesIO(payload))


def _button(button: str) -> int:
    try:
        return _BUTTONS[str(button).lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported mouse button: {button}") from exc


_KEY_ALIASES = {
    "return": "Return",
    "enter": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "tab": "Tab",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "super",
    "meta": "super",
    "win": "super",
}
_FUNCTION_KEY = re.compile(r"^f(\d{1,2})$")


def _key(key: str) -> str:
    """Map pyautogui-style key names onto xdotool keysym names."""
    name = str(key)
    alias = _KEY_ALIASES.get(name.lower())
    if alias:
        return alias
    function = _FUNCTION_KEY.match(name.lower())
    if function:
        return f"F{function.group(1)}"
    # Single characters are literal keys; anything else is already a keysym.
    return name

