"""Persist transaction facts and their causal ledger events."""

from __future__ import annotations

from .audit_recorder import AuditRecorder
from .task import TaskState
from .protocol import ReasonCode, to_primitive
from .transaction import ActionProposal, ExecutionReceipt
from .task_repository import TaskRepository


class TransactionRecorder:
    def __init__(self, tasks: TaskRepository, audit: AuditRecorder) -> None:
        self._tasks = tasks
        self._audit = audit

    def receipt(
        self,
        task_id: str,
        receipt: ExecutionReceipt,
        *,
        caused_by: tuple[str, ...],
        terminal: bool,
    ) -> None:
        self._tasks.record_receipt(task_id, receipt, terminal=terminal)
        self._audit.store.put(receipt, object_ref=receipt.execution_id)
        self._audit.append(task_id, "execution.completed", receipt.execution_id, caused_by=caused_by)

    def state(self, task_id: str, state: TaskState, *, caused_by: tuple[str, ...], snapshot_id: str) -> None:
        self._tasks.set_state(state)
        reference = self._audit.store.put(state, prefix="task-state")
        self._audit.append(
            task_id, "task.transitioned", reference, caused_by=caused_by, snapshot_id=snapshot_id
        )

    @staticmethod
    def notify_outcome(
        provider: object | None,
        task_id: str,
        *,
        status: str,
        proposal: ActionProposal,
        reason: ReasonCode,
    ) -> bool:
        callback = getattr(provider, "record_outcome", None)
        if not callable(callback):
            return True
        try:
            callback(
                task_id,
                status=status,
                execution={"proposal": to_primitive(proposal), "delivered": False},
                reason=reason,
            )
        except Exception:
            return False
        return True

    @staticmethod
    def notify_receipt(provider: object | None, task_id: str, receipt: ExecutionReceipt) -> bool:
        callback = getattr(provider, "record_execution", None)
        if not callable(callback):
            return True
        try:
            callback(task_id, receipt)
        except Exception:
            return False
        return True
