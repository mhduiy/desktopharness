"""Evidence facts and assertion conclusions."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping
from .protocol import SCHEMA_VERSION
from .task import AssertionSpec
class AssertionStatus(StrEnum):
    PASSED="passed"; FAILED="failed"; UNKNOWN="unknown"; CONFLICT="conflict"
class EvidenceConfidence(StrEnum):
    DETERMINISTIC="deterministic"; DERIVED="derived"; PROBABILISTIC="probabilistic"; MODEL_CLAIM="model-claim"; HUMAN_ANNOTATION="human-annotation"
@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str; source: str; captured_at: str; subject: Mapping[str, Any]; facts: Mapping[str, Any]; quality: EvidenceConfidence
    artifact_ref: str | None=None; schema_version: str=SCHEMA_VERSION
@dataclass(frozen=True, slots=True)
class ExcludedEvidence:
    evidence_id: str; reason: str
@dataclass(frozen=True, slots=True)
class AssertionResult:
    assertion_id: str; expression: AssertionSpec; status: AssertionStatus; evidence_refs: tuple[str, ...]; evaluated_at: str; reason: str
    excluded_evidence: tuple[ExcludedEvidence, ...]=(); schema_version: str=SCHEMA_VERSION
