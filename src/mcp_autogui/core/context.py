"""Bounded projection passed from Core to a proposal provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .desktop import FrameReference
from .protocol import SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ModelContext:
    model_context_id: str
    task_id: str
    based_on_snapshot: str
    frame: FrameReference | None
    goal: str
    current_step: int
    pending_assertions: tuple[str, ...]
    recent_execution_receipt: Mapping[str, Any] | None
    assertion_feedback: tuple[Mapping[str, Any], ...]
    constraints: Mapping[str, Any]
    ledger_event_refs: tuple[str, ...]
    spatial_projection: Mapping[str, Any] = field(default_factory=dict)
    strategy: str = "compact"
    recent_frame_refs: tuple[str, ...] = ()
    primary_attribution: Mapping[str, Any] | None = None
    projection_limits: Mapping[str, int] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
