"""Persist transaction facts and their causal ledger events."""

from __future__ import annotations

from .audit_recorder import AuditRecorder
from .models import ActionProposal, ExecutionReceipt, PolicyDecision, TaskState
from .task_repository import TaskRepository


class TransactionRecorder:
    def __init__(self, tasks: TaskRepository, audit: AuditRecorder) -> None:
        self._tasks = tasks
        self._audit = audit

    def decision(
        self,
        task_id: str,
        proposal: ActionProposal,
        decision: PolicyDecision,
        *,
        caused_by: tuple[str, ...],
        snapshot_id: str,
    ) -> str:
        reference = self._audit.store.put(decision, prefix="policy-decision")
        self._tasks.decisions[proposal.proposal_id] = decision
        self._tasks.decision_refs[proposal.proposal_id] = reference
        self._audit.append(
            task_id,
            "decision.created",
            reference,
            caused_by=caused_by,
            snapshot_id=snapshot_id,
            debug_ref=decision.debug_ref,
        )
        return reference

    def receipt(
        self,
        task_id: str,
        receipt: ExecutionReceipt,
        *,
        caused_by: tuple[str, ...],
        terminal: bool,
    ) -> None:
        self._tasks.latest_receipts[task_id] = receipt
        if terminal:
            self._tasks.terminal_receipts[receipt.proposal_id] = receipt
        self._audit.store.put(receipt, object_ref=receipt.execution_id)
        self._audit.append(task_id, "execution.completed", receipt.execution_id, caused_by=caused_by)

    def state(self, task_id: str, state: TaskState, *, caused_by: tuple[str, ...], snapshot_id: str) -> None:
        self._tasks.states[task_id] = state
        reference = self._audit.store.put(state, prefix="task-state")
        self._audit.append(
            task_id, "task.transitioned", reference, caused_by=caused_by, snapshot_id=snapshot_id
        )
