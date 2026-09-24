"""X11/EWMH raw desktop to finite CanonicalSnapshot adapter.

Only ``_NET_*``/EWMH properties and X11 geometry are read; nothing here knows
about a specific window manager.  Two independent stacking sources are merged:

* ``_NET_CLIENT_LIST_STACKING`` is authoritative for *managed* windows and is
  ordered bottom-to-top per the EWMH spec.
* ``xwininfo -root -tree`` is the X server's own child order, which is the only
  place where unmanaged (override-redirect) windows — menus, tooltips, splash
  or lock surfaces — appear.  They can cover a target while being invisible to
  EWMH, so they are carried as conservative occlusion overlays.

Locale note: ``xwininfo`` labels are parsed under ``LC_ALL=C`` (the machines we
target run zh_CN), while window titles always come from ``xprop``'s
``_NET_WM_NAME`` with the ambient locale, because forcing C mangles non-ASCII
titles.  Subprocess decoding is pinned to UTF-8 for the same reason.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ...core.models import (
    AdapterCapabilities,
    AdapterDescriptor,
    CanonicalSnapshot,
    CanonicalWindowFact,
    CoordinateSpace,
    OutputFact,
    Point,
    Rect,
    StackingCapabilities,
    StackingModel,
    WindowRole,
    new_id,
    utc_now,
)
from ...core.store import ObjectStore


from ..x11_commands import Runner, run_command


COORDINATE_SPACE_ID = "desktop-logical"
MIN_OVERLAY_SIZE = 32.0
_WINDOW_PROPERTIES = (
    "_NET_WM_NAME",
    "WM_NAME",
    "WM_CLASS",
    "_NET_WM_STATE",
    "_NET_WM_WINDOW_TYPE",
    "_NET_WM_DESKTOP",
    "_NET_FRAME_EXTENTS",
)
_ALL_DESKTOPS = 4294967295
_ROLE_PRIORITY = (
    ("_NET_WM_WINDOW_TYPE_DESKTOP", WindowRole.DESKTOP),
    ("DESKTOP", WindowRole.DESKTOP),
    ("_NET_WM_WINDOW_TYPE_DOCK", WindowRole.PANEL),
    ("DOCK", WindowRole.PANEL),
    ("TOOLBAR", WindowRole.PANEL),
    ("MENU", WindowRole.PANEL),
    ("DIALOG", WindowRole.DIALOG),
    ("UTILITY", WindowRole.DIALOG),
    ("SPLASH", WindowRole.OVERLAY),
    ("LOCKSCREEN", WindowRole.LOCKSCREEN),
    ("LOCK_SCREEN", WindowRole.LOCKSCREEN),
)
_PROPERTY_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_]+)\((?P<type>[^)]*)\)\s*=\s*(?P<value>.*)$"
)
_TREE_NODE = re.compile(
    r"^(?P<indent> *)(?P<id>0x[0-9a-fA-F]+) \"(?P<title>.*)\": "
    r"\((?P<classes>.*)\)\s+"
    r"(?P<width>\d+)x(?P<height>\d+)[+-]-?\d+[+-]-?\d+\s+"
    r"\+(?P<abs_x>-?\d+)\+(?P<abs_y>-?\d+)\s*$"
)
_TREE_CHILDREN = re.compile(r"^(?P<indent> *)(?P<count>\d+) children?:")
_OUTPUT = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+) connected (?:primary )?"
    r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
)
_CURRENT_MODE = re.compile(r"current (?P<width>\d+) x (?P<height>\d+)")
_INT_PROPERTY = re.compile(r"-?\d+")


@dataclass(frozen=True, slots=True)
class TreeNode:
    """One window as reported by ``xwininfo -root -tree``."""

    indent: int
    window_id: str
    title: str
    window_class: str | None
    geometry: Rect


def parse_root_geometry(text: str) -> Rect:
    geometry = re.search(r"-geometry (\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", text)
    if geometry:
        width, height, x, y = geometry.groups()
        return Rect(float(x), float(y), float(width), float(height))
    lines = parse_labeled_values(text)
    if "Width" in lines and "Height" in lines:
        return Rect(
            float(lines.get("Absolute upper-left X", 0)),
            float(lines.get("Absolute upper-left Y", 0)),
            float(lines["Width"]),
            float(lines["Height"]),
        )
    raise ValueError("unable to determine root window geometry")


def parse_labeled_values(text: str) -> dict[str, str]:
    """Parse ``Label: value`` lines, tolerating the alignment xwininfo uses."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        head, separator, tail = line.partition(":")
        if not separator:
            continue
        values[head.strip()] = tail.strip()
    return values


def parse_stacking(text: str) -> tuple[tuple[str, ...], str | None]:
    """Return window ids bottom-to-top plus the active window id."""
    stacking: tuple[str, ...] = ()
    active: str | None = None
    for line in text.splitlines():
        if "_NET_CLIENT_LIST_STACKING" in line:
            stacking = tuple(re.findall(r"0x[0-9a-fA-F]+", line))
        elif "_NET_ACTIVE_WINDOW" in line:
            found = re.findall(r"0x[0-9a-fA-F]+", line)
            active = found[0] if found else None
    return stacking, active


def parse_properties(text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in text.splitlines():
        match = _PROPERTY_LINE.match(line.strip())
        if match:
            properties[match.group("name")] = match.group("value").strip()
    return properties


def parse_cursor(text: str) -> Point | None:
    values = {
        match.group("key"): match.group("value")
        for match in re.finditer(r"^(?P<key>[A-Za-z_]+)=(?P<value>-?\d+)\s*$", text, re.M)
    }
    if "X" not in values or "Y" not in values:
        return None
    return Point(float(values["X"]), float(values["Y"]))


def parse_outputs(text: str) -> tuple[Rect, tuple[OutputFact, ...]]:
    outputs: list[OutputFact] = []
    for line in text.splitlines():
        match = _OUTPUT.match(line.strip())
        if not match:
            continue
        outputs.append(
            OutputFact(
                output_id=match.group("name"),
                geometry=Rect(
                    float(match.group("x")),
                    float(match.group("y")),
                    float(match.group("width")),
                    float(match.group("height")),
                ),
                scale=1.0,
            )
        )
    root = _CURRENT_MODE.search(text)
    if root:
        bounds = Rect(0.0, 0.0, float(root.group("width")), float(root.group("height")))
    elif outputs:
        left = min(item.geometry.x for item in outputs)
        top = min(item.geometry.y for item in outputs)
        right = max(item.geometry.x + item.geometry.width for item in outputs)
        bottom = max(item.geometry.y + item.geometry.height for item in outputs)
        bounds = Rect(left, top, right - left, bottom - top)
    else:
        raise ValueError("xrandr reported neither a current mode nor a connected output")
    return bounds, tuple(outputs)


def parse_window_tree(text: str) -> tuple[TreeNode, ...]:
    """Flatten ``xwininfo -root -tree`` keeping indentation for nesting."""
    nodes: list[TreeNode] = []
    for line in text.splitlines():
        match = _TREE_NODE.match(line)
        if not match:
            continue
        classes = re.findall(r'"([^"]*)"', match.group("classes"))
        nodes.append(
            TreeNode(
                indent=len(match.group("indent")),
                window_id=match.group("id"),
                title=match.group("title"),
                window_class=classes[0] if classes else None,
                geometry=Rect(
                    float(match.group("abs_x")),
                    float(match.group("abs_y")),
                    float(match.group("width")),
                    float(match.group("height")),
                ),
            )
        )
    return tuple(nodes)


def top_level_with_descendants(nodes: Sequence[TreeNode]) -> tuple[tuple[TreeNode, tuple[str, ...]], ...]:
    """Group the tree into top-level windows and the ids nested below each."""
    if not nodes:
        return ()
    base_indent = min(node.indent for node in nodes)
    groups: list[tuple[TreeNode, list[str]]] = []
    current: list[str] | None = None
    for node in nodes:
        if node.indent == base_indent:
            current = [node.window_id]
            groups.append((node, current))
            continue
        if current is not None:
            current.append(node.window_id)
    return tuple((node, tuple(ids)) for node, ids in groups)


def parse_window_geometry(text: str) -> tuple[Rect, bool | None]:
    values = parse_labeled_values(text)
    try:
        geometry = Rect(
            float(values["Absolute upper-left X"]),
            float(values["Absolute upper-left Y"]),
            float(values["Width"]),
            float(values["Height"]),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("xwininfo did not report window geometry") from exc
    map_state = values.get("Map State")
    visible = None if map_state is None else map_state == "IsViewable"
    return geometry, visible


def frame_extents(properties: dict[str, str]) -> tuple[float, float, float, float]:
    raw = properties.get("_NET_FRAME_EXTENTS")
    if not raw:
        return (0.0, 0.0, 0.0, 0.0)
    numbers = [float(item) for item in _INT_PROPERTY.findall(raw)[:4]]
    if len(numbers) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    left, right, top, bottom = numbers
    return (left, top, right, bottom)


def window_role(properties: dict[str, str]) -> WindowRole:
    blob = " ".join(
        item.upper()
        for item in (
            properties.get("_NET_WM_WINDOW_TYPE", ""),
            properties.get("WM_CLASS", ""),
        )
    )
    for token, role in _ROLE_PRIORITY:
        if token in blob:
            return role
    return WindowRole.NORMAL


def unquote(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        stripped = stripped[1:-1]
    return stripped or None


class X11CompositorAdapter:
    """X11/EWMH implementation of the compositor port."""

    adapter_id = "x11"

    def __init__(
        self,
        *,
        runner: Runner = run_command,
        artifact_store: ObjectStore | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._run = runner
        self._artifacts = artifact_store or ObjectStore()
        self._timeout = timeout
        self._latest: CanonicalSnapshot | None = None

    # -- capability surface -------------------------------------------------

    @property
    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=self.adapter_id,
            capabilities=AdapterCapabilities(
                window_tree=True,
                cursor_position=True,
                desktop_geometry=True,
                stacking=StackingCapabilities(
                    model=StackingModel.TOTAL_ORDER,
                    z_index=True,
                    is_above=True,
                    occlusion=True,
                    hit_test=True,
                ),
                active_window=True,
                workspace=True,
                window_identity="best-effort",
            ),
        )

    @property
    def latest_snapshot(self) -> CanonicalSnapshot | None:
        return self._latest

    # -- raw queries --------------------------------------------------------

    def _text(self, argv: Sequence[str], *, c_locale: bool = False) -> str:
        completed = self._run(list(argv), c_locale=c_locale, timeout=self._timeout)
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            raise RuntimeError(
                f"X11 query failed ({completed.returncode}): {' '.join(argv)}: "
                f"{detail[-1] if detail else 'no stderr'}"
            )
        return completed.stdout or ""

    def get_window_tree(self) -> object:
        """Return the parsed X window tree (unmanaged windows included)."""
        nodes = parse_window_tree(self._text(["xwininfo", "-root", "-tree"], c_locale=True))
        return {
            "windows": [
                {
                    "window_id": node.window_id,
                    "title": node.title,
                    "window_class": node.window_class,
                    "geometry": [node.geometry.x, node.geometry.y, node.geometry.width, node.geometry.height],
                    "indent": node.indent,
                }
                for node in nodes
            ]
        }

    def get_cursor_position(self) -> Point | None:
        return parse_cursor(self._text(["xdotool", "getmouselocation", "--shell"]))

    def get_desktop_geometry(self) -> Rect:
        bounds, _ = parse_outputs(self._text(["xrandr", "--current"]))
        return bounds

    def active_window_facts(self) -> dict[str, object] | None:
        """Lightweight two-query probe of the active window.

        Post-action polling must not run a full ``observe()`` per iteration.
        """
        _, active_id = parse_stacking(self._text(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
        if active_id is None:
            return None
        properties = parse_properties(
            self._text(["xprop", "-id", active_id, "_NET_WM_NAME", "WM_CLASS"])
        )
        raw_class = properties.get("WM_CLASS")
        app_id = unquote(raw_class.split(",")[0]) if raw_class else None
        return {
            "window_id": active_id,
            "appId": app_id,
            "title": unquote(properties.get("_NET_WM_NAME")),
        }

    # -- observation --------------------------------------------------------

    def observe(self) -> CanonicalSnapshot:
        return self.observe_raw(
            {
                "root": self._text(["xwininfo", "-root"], c_locale=True),
                "cursor": self._text(["xdotool", "getmouselocation", "--shell"]),
                "xrandr": self._text(["xrandr", "--current"]),
                "stacking": self._text(
                    ["xprop", "-root", "_NET_CLIENT_LIST_STACKING", "_NET_ACTIVE_WINDOW"]
                ),
                "tree": self._text(["xwininfo", "-root", "-tree"], c_locale=True),
            }
        )

    def observe_raw(self, raw: dict[str, str]) -> CanonicalSnapshot:
        """Normalize already captured command output without new transport reads."""
        bounds, outputs = parse_outputs(raw["xrandr"])
        root_bounds = parse_root_geometry(raw["root"])
        if (root_bounds.width, root_bounds.height) != (bounds.width, bounds.height):
            # The root window is the union of the outputs; trust the server when
            # they disagree (rotated or scaled layouts report differently).
            bounds = Rect(root_bounds.x, root_bounds.y, root_bounds.width, root_bounds.height)
        stacking, active_id = parse_stacking(raw["stacking"])
        cursor = parse_cursor(raw["cursor"])
        nodes = parse_window_tree(raw["tree"])

        windows: list[CanonicalWindowFact] = []
        skipped: list[str] = []
        overlay_candidates: list[str] = []
        for index, window_id in enumerate(stacking):
            properties = parse_properties(self._query_properties(window_id, raw))
            try:
                geometry, visible = parse_window_geometry(
                    self._query_geometry(window_id, raw)
                )
            except ValueError:
                skipped.append(window_id)
                continue
            left, top, right, bottom = frame_extents(properties)
            frame = Rect(
                geometry.x - left,
                geometry.y - top,
                geometry.width + left + right,
                geometry.height + top + bottom,
            )
            if "_NET_WM_STATE_HIDDEN" in properties.get("_NET_WM_STATE", ""):
                visible = False
            app_id = unquote(properties.get("WM_CLASS", "").split(",")[0]) if properties.get("WM_CLASS") else None
            title = unquote(properties.get("_NET_WM_NAME")) or unquote(properties.get("WM_NAME"))
            windows.append(
                CanonicalWindowFact(
                    window_id=window_id,
                    geometry=frame,
                    app_id=app_id,
                    title=title,
                    visible=visible,
                    active=None if active_id is None else window_id == active_id,
                    z_index=float(index),
                    workspace_id=_workspace(properties),
                    output_id=_output_for(frame, outputs),
                    role=window_role(properties),
                )
            )

        for node, descendants in top_level_with_descendants(nodes):
            if set(descendants) & set(stacking):
                continue
            if node.geometry.width < MIN_OVERLAY_SIZE or node.geometry.height < MIN_OVERLAY_SIZE:
                continue
            overlay_candidates.append(node.window_id)

        overlays = tuple(
            window_id
            for window_id in overlay_candidates
            if self._overlay_is_visible(window_id, raw)
        )
        overlay_geometry = {
            node.window_id: node.geometry
            for node in nodes
            if node.window_id in overlays
        }

        environment_payload = {
            "windows": [
                [
                    item.window_id,
                    item.app_id,
                    item.title,
                    item.geometry.x,
                    item.geometry.y,
                    item.geometry.width,
                    item.geometry.height,
                    item.visible,
                    item.active,
                    item.z_index,
                    item.workspace_id,
                ]
                for item in windows
            ]
        }
        artifacts = {
            "commands": dict(raw),
            "queried": {
                key: value
                for key, value in raw.items()
                if key.startswith("prop-") or key.startswith("xwininfo-")
            },
            "skipped_windows": skipped,
            "overlays": {
                window_id: [geometry.x, geometry.y, geometry.width, geometry.height]
                for window_id, geometry in overlay_geometry.items()
            },
        }
        coordinate_version = "sha256:" + hashlib.sha256(
            json.dumps(
                {
                    "root": [bounds.x, bounds.y, bounds.width, bounds.height],
                    "outputs": [
                        [item.output_id, item.geometry.x, item.geometry.y, item.geometry.width, item.geometry.height]
                        for item in outputs
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        raw_ref = self._artifacts.put(artifacts, prefix="x11-observation")
        snapshot = CanonicalSnapshot(
            snapshot_id=new_id("snapshot"),
            captured_at=utc_now(),
            environment_version="sha256:"
            + hashlib.sha256(
                json.dumps(environment_payload, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            coordinate_space=CoordinateSpace(COORDINATE_SPACE_ID, bounds, coordinate_version),
            outputs=outputs,
            cursor=cursor,
            windows=tuple(windows),
            raw_artifact_ref=raw_ref,
        )
        self._latest = snapshot
        return snapshot

    def _query_properties(self, window_id: str, raw: dict[str, str]) -> str:
        key = f"prop-{window_id}"
        if key not in raw:
            raw[key] = self._text(["xprop", "-id", window_id, *_WINDOW_PROPERTIES])
        return raw[key]

    def _query_geometry(self, window_id: str, raw: dict[str, str]) -> str:
        key = f"xwininfo-{window_id}"
        if key not in raw:
            raw[key] = self._text(["xwininfo", "-id", window_id], c_locale=True)
        return raw[key]

    def _overlay_is_visible(self, window_id: str, raw: dict[str, str]) -> bool:
        """Unmanaged windows are only blocking when the server says they are mapped."""
        try:
            _, visible = parse_window_geometry(self._query_geometry(window_id, raw))
        except ValueError:
            return False
        return visible is True

    # -- spatial queries ----------------------------------------------------

    def _current(self, snapshot: CanonicalSnapshot | None) -> CanonicalSnapshot:
        current = snapshot or self._latest
        if current is None:
            current = self.observe()
        return current

    def _overlay_rects(self, snapshot: CanonicalSnapshot) -> tuple[Rect, ...]:
        if not snapshot.raw_artifact_ref:
            return ()
        artifact = self._artifacts.get(snapshot.raw_artifact_ref)
        if not isinstance(artifact, dict):
            return ()
        overlays = artifact.get("overlays") or {}
        return tuple(
            Rect(float(item[0]), float(item[1]), float(item[2]), float(item[3]))
            for item in overlays.values()
            if isinstance(item, (list, tuple)) and len(item) == 4
        )

    def hit_test(self, point: Point, snapshot: CanonicalSnapshot | None = None) -> str | None:
        """Topmost managed window at ``point``.

        Returns ``None`` when an unmanaged overlay covers the point: the caller
        must treat that as "cannot identify the target" and refuse rather than
        inject input into whatever is actually on top.
        """
        current = self._current(snapshot)
        for rect in self._overlay_rects(current):
            if rect.contains(point):
                return None
        for window in reversed(current.windows):
            if window.visible is not False and window.geometry.contains(point):
                return window.window_id
        return None

    def topmost_window_at(
        self, point: Point, snapshot: CanonicalSnapshot | None = None
    ) -> str | None:
        return self.hit_test(point, snapshot)

    def _stack_index(self, current: CanonicalSnapshot, window_id: str) -> float | None:
        window = current.window(window_id)
        return None if window is None else window.z_index

    def is_above(
        self,
        window_a: str,
        window_b: str,
        snapshot: CanonicalSnapshot | None = None,
    ) -> bool | None:
        current = self._current(snapshot)
        first = self._stack_index(current, window_a)
        second = self._stack_index(current, window_b)
        if first is None or second is None:
            return None
        return first > second

    def occluded(
        self,
        window_id: str,
        region: Rect,
        snapshot: CanonicalSnapshot | None = None,
    ) -> bool | None:
        current = self._current(snapshot)
        target = current.window(window_id)
        if target is None:
            return None
        for rect in self._overlay_rects(current):
            if _intersects(rect, region):
                return True
        for window in current.windows:
            if window.window_id == window_id or window.visible is False:
                continue
            if window.z_index is not None and target.z_index is not None:
                if window.z_index > target.z_index and _intersects(window.geometry, region):
                    return True
        return False


def _workspace(properties: dict[str, str]) -> str | None:
    raw = properties.get("_NET_WM_DESKTOP")
    if not raw:
        return None
    numbers = _INT_PROPERTY.findall(raw)
    if not numbers:
        return None
    value = int(numbers[0])
    if value == _ALL_DESKTOPS or value < 0:
        return None
    return str(value)


def _output_for(geometry: Rect, outputs: Sequence[OutputFact]) -> str | None:
    centre = Point(geometry.x + geometry.width / 2.0, geometry.y + geometry.height / 2.0)
    for output in outputs:
        if output.geometry.contains(centre):
            return output.output_id
    return outputs[0].output_id if len(outputs) == 1 else None


def _intersects(left: Rect, right: Rect) -> bool:
    return not (
        left.x + left.width <= right.x
        or right.x + right.width <= left.x
        or left.y + left.height <= right.y
        or right.y + right.height <= left.y
    )
