"""Shared protocol primitives with no desktop or adapter dependency."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


SCHEMA_VERSION = "1"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_primitive(value: Any) -> Any:
    """Serialize protocol objects without leaking adapter-specific objects."""
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value


class ReasonCode(StrEnum):
    """Stable protocol reason codes shared by decisions and diagnostics."""

    OK = "OK"
    APPLICATION_LAUNCH_FAILED = "APPLICATION_LAUNCH_FAILED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONTROLLER_TASK_CONTRACT_INVALID = "CONTROLLER_TASK_CONTRACT_INVALID"
    COORDINATE_SPACE_CHANGED = "COORDINATE_SPACE_CHANGED"
    CURSOR_ORIGIN_CHANGED = "CURSOR_ORIGIN_CHANGED"
    EVIDENCE_COLLECTION_FAILED = "EVIDENCE_COLLECTION_FAILED"
    EXECUTOR_ACTION_FAILED = "EXECUTOR_ACTION_FAILED"
    EXECUTOR_ACTION_MISMATCH = "EXECUTOR_ACTION_MISMATCH"
    HIT_TEST_CHANGED = "HIT_TEST_CHANGED"
    INSUFFICIENT_GROUND_TRUTH = "INSUFFICIENT_GROUND_TRUTH"
    INVALID_COORDINATE_SPACE = "INVALID_COORDINATE_SPACE"
    MECHANICAL_PERMISSION_DENIED = "MECHANICAL_PERMISSION_DENIED"
    MODEL_PLANNING_INVALID = "MODEL_PLANNING_INVALID"
    MODEL_PROTOCOL_INVALID = "MODEL_PROTOCOL_INVALID"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    OUTCOME_POSTCONDITION_FAILED = "OUTCOME_POSTCONDITION_FAILED"
    OUTSIDE_DESKTOP = "OUTSIDE_DESKTOP"
    POLICY_DENIED = "POLICY_DENIED"
    ROOT_CAUSE_UNRESOLVED = "ROOT_CAUSE_UNRESOLVED"
    SEMANTIC_POLICY_DENIED = "SEMANTIC_POLICY_DENIED"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    TARGET_DISAPPEARED = "TARGET_DISAPPEARED"
    TARGET_GEOMETRY_INVALIDATED = "TARGET_GEOMETRY_INVALIDATED"
    TARGET_IDENTITY_CHANGED = "TARGET_IDENTITY_CHANGED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_OCCLUDED = "TARGET_OCCLUDED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    USER_CONFIRMED = "USER_CONFIRMED"


class OperationFailure(RuntimeError):
    """Typed failure from an application operation with recovery guidance."""

    def __init__(
        self,
        reason_code: ReasonCode,
        message: str,
        *,
        retry: bool,
        required_action: str,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retry = retry
        self.required_action = required_action
