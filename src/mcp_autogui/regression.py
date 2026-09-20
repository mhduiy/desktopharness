"""Small, deterministic helpers for real-desktop regression drivers.

The driver must derive target coordinates from the observation captured for
*that* iteration.  Keeping that calculation here prevents a test fixture from
accidentally retaining a desktop-absolute coordinate after a window moves.
"""

from __future__ import annotations

from collections.abc import Mapping


def window_relative_point(
    geometry: Mapping[str, float],
    relative_x: float,
    relative_y: float,
) -> dict[str, float]:
    """Return a desktop-logical point at a normalized position in a window.

    ``relative_x`` and ``relative_y`` are fractions in the inclusive range
    0..1.  A caller should obtain ``geometry`` from the same snapshot used to
    create its task contract.
    """
    if not 0.0 <= relative_x <= 1.0 or not 0.0 <= relative_y <= 1.0:
        raise ValueError("relative coordinates must be between 0 and 1")
    try:
        x = float(geometry["x"])
        y = float(geometry["y"])
        width = float(geometry["width"])
        height = float(geometry["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("window geometry requires numeric x, y, width, and height") from exc
    if width <= 0 or height <= 0:
        raise ValueError("window geometry width and height must be positive")
    return {"x": x + width * relative_x, "y": y + height * relative_y}
