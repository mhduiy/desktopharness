"""Audit and diagnostic protocol facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .protocol import ReasonCode, SCHEMA_VERSION


class AttributionEventKind(StrEnum):
    ERROR = "error"
    SAFE_REFUSAL = "safe-refusal"
    EXTERNAL_CHANGE = "external-change"
    INCOMPLETE = "incomplete"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


class AttributionEvidenceStatus(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    INSUFFICIENT = "insufficient"


class AttributionStage(StrEnum):
    PERCEPTION = "perception"
    PLANNING = "planning"
    GROUNDING = "grounding"
    PROTOCOL = "protocol"
    EXECUTION = "execution"
    ENVIRONMENT = "environment"
    OUTCOME = "outcome"
    EVIDENCE_COLLECTION = "evidence-collection"
    ASSERTION_EVALUATION = "assertion-evaluation"
    STATE_TRANSITION = "state-transition"


class AttributionOwner(StrEnum):
    MODEL = "model"
    EXECUTOR = "executor"
    ENVIRONMENT = "environment"
    EVIDENCE_PROVIDER = "evidence-provider"
    ASSERTION_EVALUATOR = "assertion-evaluator"
    TASK_STATE_REDUCER = "task-state-reducer"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Attribution:
    attribution_id: str
    event_kind: AttributionEventKind
    stage: AttributionStage
    owner: AttributionOwner
    code: ReasonCode
    evidence_status: AttributionEvidenceStatus
    primary: bool
    summary: str
    evidence_refs: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.code, ReasonCode):
            raise TypeError("Attribution.code must be a ReasonCode")


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    event_id: str
    task_id: str
    sequence: int
    occurred_at: str
    event_type: str
    epistemic_type: str
    object_ref: str
    caused_by: tuple[str, ...] = ()
    snapshot_id: str | None = None
    artifact_refs: tuple[str, ...] = ()
    debug_ref: str | None = None
    schema_version: str = SCHEMA_VERSION
