"""Canonical desktop observations and geometry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .protocol import SCHEMA_VERSION


class WindowRole(StrEnum):
    NORMAL = "normal"
    DESKTOP = "desktop"
    PANEL = "panel"
    OVERLAY = "overlay"
    LOCKSCREEN = "lockscreen"
    DIALOG = "dialog"
    UNKNOWN = "unknown"


class StackingModel(StrEnum):
    TOTAL_ORDER = "total-order"
    PARTIAL_ORDER = "partial-order"
    HIT_TEST = "hit-test"
    TOPMOST_ONLY = "topmost-only"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("rectangle dimensions cannot be negative")

    def contains(self, point: Point) -> bool:
        return self.x <= point.x < self.x + self.width and self.y <= point.y < self.y + self.height


@dataclass(frozen=True, slots=True)
class CoordinateSpace:
    id: str
    bounds: Rect
    version: str | None = None


@dataclass(frozen=True, slots=True)
class OutputFact:
    output_id: str
    geometry: Rect
    scale: float | None = None


@dataclass(frozen=True, slots=True)
class CanonicalWindowFact:
    window_id: str
    geometry: Rect
    app_id: str | None = None
    title: str | None = None
    visible: bool | None = None
    active: bool | None = None
    z_index: float | None = None
    workspace_id: str | None = None
    output_id: str | None = None
    role: WindowRole = WindowRole.UNKNOWN


@dataclass(frozen=True, slots=True)
class StackingCapabilities:
    model: StackingModel
    z_index: bool = False
    is_above: bool = False
    occlusion: bool = False
    hit_test: bool = False


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    window_tree: bool
    cursor_position: bool
    desktop_geometry: bool
    stacking: StackingCapabilities
    active_window: bool = False
    workspace: bool = False
    window_identity: str = "unavailable"
    child_controls: bool = False
    window_text: bool = False


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    adapter_id: str
    capabilities: AdapterCapabilities
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CanonicalSnapshot:
    snapshot_id: str
    captured_at: str
    environment_version: str
    coordinate_space: CoordinateSpace
    outputs: tuple[OutputFact, ...]
    cursor: Point | None
    windows: tuple[CanonicalWindowFact, ...]
    raw_artifact_ref: str | None = None
    schema_version: str = SCHEMA_VERSION

    def window(self, window_id: str) -> CanonicalWindowFact | None:
        return next((item for item in self.windows if item.window_id == window_id), None)

    def active_window(self) -> CanonicalWindowFact | None:
        return next((item for item in self.windows if item.active is True), None)


@dataclass(frozen=True, slots=True)
class FrameReference:
    frame_id: str
    captured_at: str
    image_ref: str
    pixel_size: tuple[int, int]
    from_space: str = "frame-pixel"
    to_space: str = "desktop-logical"
    transform_ref: str | None = None
    schema_version: str = SCHEMA_VERSION
