"""Proposal, policy and executor transaction facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .desktop import Point, Rect
from .protocol import ReasonCode, SCHEMA_VERSION


class ActionType(StrEnum):
    POINTER_MOVE = "pointer.move"
    POINTER_CLICK = "pointer.click"
    POINTER_DOUBLE_CLICK = "pointer.double_click"
    POINTER_DRAG = "pointer.drag"
    POINTER_SCROLL = "pointer.scroll"
    KEYBOARD_KEY = "keyboard.key"
    KEYBOARD_SHORTCUT = "keyboard.shortcut"
    KEYBOARD_TEXT = "keyboard.text"
    PLATFORM_INVOKE = "platform.invoke"
    APPLICATION_LAUNCH = "application.launch"
    DONE = "done"


class PolicyStatus(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"
    INVALID = "invalid"
    STALE = "stale"


class ExecutionStatus(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Action:
    type: ActionType
    coordinate: Point | None = None
    coordinate_space: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        coordinate_actions = {
            ActionType.POINTER_MOVE,
            ActionType.POINTER_CLICK,
            ActionType.POINTER_DOUBLE_CLICK,
            ActionType.POINTER_DRAG,
        }
        if self.type in coordinate_actions and self.coordinate is None:
            raise ValueError(f"{self.type.value} requires a coordinate")
        if self.coordinate is not None and not self.coordinate_space:
            raise ValueError("coordinate actions must declare coordinate_space")


@dataclass(frozen=True, slots=True)
class ActionProposal:
    proposal_id: str
    source: str
    based_on_snapshot: str
    action: Action
    actions: tuple[Action, ...] = ()
    claimed_intent: str | None = None
    debug_ref: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.actions and self.actions[0] != self.action:
            raise ValueError("proposal.action must equal the first action in actions")

    @property
    def action_sequence(self) -> tuple[Action, ...]:
        """Full model proposal, with legacy single-action compatibility."""
        return self.actions or (self.action,)


@dataclass(frozen=True, slots=True)
class SemanticTag:
    tag: str
    source: str
    evidence_ref: str | None
    confidence: "EvidenceConfidence"


@dataclass(frozen=True, slots=True)
class SemanticResolution:
    semantic_resolution_id: str
    proposal_id: str
    status: str
    tags: tuple[SemanticTag, ...]
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ProposalGuard:
    guard_id: str
    proposal_id: str
    derived_from_snapshot: str
    coordinate_space_id: str | None = None
    coordinate_space_version: str | None = None
    target_window_id: str | None = None
    target_identity: Mapping[str, Any] = field(default_factory=dict)
    identity_required: bool = False
    required_visible: bool = False
    required_active: bool = False
    expected_geometry: Rect | None = None
    geometry_policy: str | None = None
    hit_test_point: Point | None = None
    required_hit_window_id: str | None = None
    cursor_origin: Point | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    proposal_id: str
    status: PolicyStatus
    reason_code: ReasonCode
    resolved_target: Mapping[str, Any] = field(default_factory=dict)
    guard_ref: str | None = None
    semantic_resolution_ref: str | None = None
    debug_ref: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, ReasonCode):
            raise TypeError("PolicyDecision.reason_code must be a ReasonCode")


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: str
    proposal_id: str
    status: ExecutionStatus
    executed_action: Action | None
    started_at: str
    finished_at: str
    error_code: ReasonCode | None = None
    debug_ref: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.error_code is not None and not isinstance(self.error_code, ReasonCode):
            raise TypeError("ExecutionReceipt.error_code must be a ReasonCode or None")
