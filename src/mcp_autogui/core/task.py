"""Task contract and lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .protocol import SCHEMA_VERSION


class TaskStatus(StrEnum):
    RUNNING = "running"
    NEEDS_CONFIRMATION = "needs-confirmation"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TaskPermissions:
    actions: frozenset["ActionType"]
    semantic_intents: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class AssertionSpec:
    assertion_id: str
    path: str
    operator: str
    expected: Any = None
    required: bool = True
    recoverable: bool = True
    subject: Mapping[str, Any] = field(default_factory=dict)
    providers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskLimits:
    max_steps: int = 10
    max_retries: int = 1

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_retries < 0:
            raise ValueError("invalid task limits")


@dataclass(frozen=True, slots=True)
class TaskContract:
    task_id: str
    goal: str
    permissions: TaskPermissions
    assertions: tuple[AssertionSpec, ...] = ()
    limits: TaskLimits = field(default_factory=TaskLimits)
    policy_profile: str = "desktop-safe-default"
    verification_profile: str = "default"
    policy_overrides: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: str
    status: TaskStatus = TaskStatus.RUNNING
    step: int = 0
    retries: int = 0
    completed_assertions: tuple[str, ...] = ()
    failed_assertions: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION


from .transaction import ActionType
