"""In-memory indexes for active task transactions."""

from __future__ import annotations

from typing import Any

from .models import (
    AssertionResult,
    CanonicalSnapshot,
    ExecutionReceipt,
    PolicyDecision,
    ProposalGuard,
    TaskContract,
    TaskState,
)


class TaskRepository:
    """Own runtime-only task indexes; persisted facts remain in the audit store."""

    def __init__(self) -> None:
        self.contracts: dict[str, TaskContract] = {}
        self.states: dict[str, TaskState] = {}
        self.latest_snapshots: dict[str, CanonicalSnapshot] = {}
        self.latest_frames: dict[str, Any] = {}
        self.proposal_tasks: dict[str, str] = {}
        self.provider_proposals: set[str] = set()
        self.provider_finalized: set[str] = set()
        self.decisions: dict[str, PolicyDecision] = {}
        self.decision_refs: dict[str, str] = {}
        self.guards: dict[str, ProposalGuard] = {}
        self.latest_receipts: dict[str, ExecutionReceipt] = {}
        self.terminal_receipts: dict[str, ExecutionReceipt] = {}
        self.latest_results: dict[str, tuple[AssertionResult, ...]] = {}

    def clear_task(self, task_id: str) -> None:
        self.contracts.pop(task_id, None)
        self.states.pop(task_id, None)
        self.latest_snapshots.pop(task_id, None)
        self.latest_frames.pop(task_id, None)
        self.latest_receipts.pop(task_id, None)
        self.latest_results.pop(task_id, None)
        for proposal_id, owner in tuple(self.proposal_tasks.items()):
            if owner != task_id:
                continue
            self.proposal_tasks.pop(proposal_id, None)
            self.provider_proposals.discard(proposal_id)
            self.provider_finalized.discard(proposal_id)
            self.decisions.pop(proposal_id, None)
            self.decision_refs.pop(proposal_id, None)
            self.terminal_receipts.pop(proposal_id, None)
