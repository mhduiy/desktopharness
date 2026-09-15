"""Pure reduction from controller results to the public task protocol."""

from __future__ import annotations

from typing import Any

from .core.task import TaskStatus


PUBLIC_TASK_STATUSES = frozenset(status.value for status in TaskStatus)


def reduce_public_response(
    operation: str,
    *,
    task_state: str | None,
    object_ref: str | None = None,
    error: dict[str, Any] | None = None,
    retry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map authoritative task state to the compact public response."""
    status = _public_status(task_state, error)
    return {
        "protocol_version": 2,
        "operation": operation,
        "status": status,
        "task_state": task_state,
        "object_ref": object_ref,
        "error": error,
        "retry": retry,
    }


def _public_status(task_state: str | None, error: dict[str, Any] | None) -> str:
    if error is not None:
        return TaskStatus.FAILED.value
    if task_state in PUBLIC_TASK_STATUSES:
        return task_state
    return TaskStatus.COMPLETED.value
