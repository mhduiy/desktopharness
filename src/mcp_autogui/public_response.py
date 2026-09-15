"""Pure reduction from controller results to the public task protocol."""

from __future__ import annotations

from typing import Any

from .core.task import TaskStatus


PUBLIC_TASK_STATUSES = frozenset(status.value for status in TaskStatus)


def reduce_public_response(
    operation: str,
    domain_status: str,
    *,
    task_state: str | None,
    object_ref: str | None = None,
    error: dict[str, Any] | None = None,
    retry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a domain result plus task state to the compact public response."""
    status = _public_status(domain_status, task_state, error)
    return {
        "protocol_version": 2,
        "operation": operation,
        "status": status,
        "task_state": task_state,
        "object_ref": object_ref,
        "error": error,
        "retry": retry,
    }


def _public_status(domain_status: str, task_state: str | None, error: dict[str, Any] | None) -> str:
    if error is not None or domain_status == "failed":
        return TaskStatus.FAILED.value
    if task_state in PUBLIC_TASK_STATUSES:
        return task_state
    if domain_status in PUBLIC_TASK_STATUSES:
        return domain_status
    return TaskStatus.COMPLETED.value
