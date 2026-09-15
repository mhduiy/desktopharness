"""Narrow application service for desktop-owned transactions."""

from __future__ import annotations

from .core.orchestrator import CoreOrchestrator
from .core.task import TaskContract, TaskState
from .core.transaction import PolicyDecision, PolicyStatus
from .desktop_backend import (
    DesktopTransactionResult,
    ProposalBuilder,
    RunBlocking,
)


class CoreDesktopTransactionRunner:
    """Expose one bounded Core transaction without exposing the Core runtime."""

    def __init__(self, runtime: CoreOrchestrator, run_blocking: RunBlocking) -> None:
        self._runtime = runtime
        self._run_blocking = run_blocking

    async def execute(
        self,
        contract: TaskContract,
        proposal_builder: ProposalBuilder,
    ) -> DesktopTransactionResult:
        return await self._run_blocking(self._execute, contract, proposal_builder)

    async def evaluate(self, task_id: str) -> TaskState:
        _, _, state = await self._run_blocking(self._runtime.evaluate, task_id)
        return state

    def _execute(
        self,
        contract: TaskContract,
        proposal_builder: ProposalBuilder,
    ) -> DesktopTransactionResult:
        self._runtime.register_task(contract)
        snapshot = self._runtime.observe(contract.task_id)
        proposal = proposal_builder(snapshot)
        if proposal.based_on_snapshot != snapshot.snapshot_id:
            raise ValueError("desktop proposal must reference the transaction snapshot")
        self._runtime.submit_proposal(contract.task_id, proposal)
        decision = self._runtime.decide(proposal.proposal_id)
        receipt = None
        if decision.status == PolicyStatus.ALLOW:
            execution = self._runtime.execute(proposal.proposal_id)
            if isinstance(execution, PolicyDecision):
                decision = execution
            else:
                receipt = execution
        return DesktopTransactionResult(
            snapshot=snapshot,
            proposal=proposal,
            decision=decision,
            receipt=receipt,
            state=self._runtime.status(contract.task_id),
        )
