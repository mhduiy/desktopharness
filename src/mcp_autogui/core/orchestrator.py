"""Thin coordinator for the v2 single-action transaction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from threading import RLock
from typing import Any, Mapping

from ..ports.compositor import CompositorPort
from ..ports.evidence import EvidenceProvider
from ..ports.executor import ActionExecutor
from ..ports.frame import FrameProvider
from ..ports.policy import PolicyProvider
from ..ports.proposal import ProposalProvider
from .action_gate import ActionGate
from .audit_models import (
    Attribution,
    AttributionEventKind,
    AttributionEvidenceStatus,
    AttributionOwner,
    AttributionStage,
)
from .audit_recorder import AuditRecorder
from .assertion_evaluator import AssertionEvaluator, SUPPORTED_OPERATORS
from .context_builder import ContextBuilder
from .desktop import CanonicalSnapshot
from .evidence import AssertionResult, AssertionStatus, EvidenceRecord
from .facts import require_standard_fact_path
from .ledger import EventLedger
from .protocol import OperationFailure, ReasonCode, to_primitive
from .store import ObjectStore
from .task import TaskContract, TaskState, TaskStatus
from .transaction import (
    ActionProposal,
    ActionType,
    ExecutionReceipt,
    ExecutionStatus,
    PolicyDecision,
    PolicyStatus,
    SemanticTag,
)
from .task_repository import TaskRepository
from .task_state import TaskStateReducer
from .transaction_recorder import TransactionRecorder


class CoreOrchestrator:
    """Coordinates ports without allowing adapters to call one another."""

    def __init__(
        self,
        compositor: CompositorPort,
        executor: ActionExecutor,
        *,
        proposal_provider: ProposalProvider | None = None,
        frame_provider: FrameProvider | None = None,
        evidence_providers: Sequence[EvidenceProvider] = (),
        policy_providers: Sequence[PolicyProvider] = (),
        policy_profiles: Mapping[str, Mapping[str, str]] | None = None,
        store: ObjectStore | None = None,
        ledger: EventLedger | None = None,
    ) -> None:
        self.compositor = compositor
        self.executor = executor
        self.proposal_provider = proposal_provider
        self.frame_provider = frame_provider
        self.evidence_providers = tuple(evidence_providers)
        self.policy_providers = tuple(policy_providers)
        provider_ids = [provider.provider_id for provider in self.evidence_providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("evidence provider IDs must be unique")
        for provider in self.evidence_providers:
            for path in provider.fact_paths:
                require_standard_fact_path(path)
        self._audit = AuditRecorder(store, ledger)
        self.store = self._audit.store
        self.ledger = self._audit.ledger
        self.gate = ActionGate(
            compositor.descriptor, compositor.hit_test, policy_profiles=policy_profiles
        )
        self.evaluator = AssertionEvaluator()
        self.reducer = TaskStateReducer()
        self.context_builder = ContextBuilder()
        self._tasks = TaskRepository()
        self._transactions = TransactionRecorder(self._tasks, self._audit)
        self._execution_lock = RLock()

    def register_task(self, contract: TaskContract) -> TaskState:
        if not contract.task_id or not contract.goal:
            raise ValueError("task_id and goal must not be empty")
        if contract.policy_profile not in self.gate.policy_profiles:
            raise ValueError(f"unknown policy profile: {contract.policy_profile}")
        if any(
            value not in {"allow", "confirm", "deny"}
            for value in contract.policy_overrides.values()
        ):
            raise ValueError("policy overrides must be allow, confirm, or deny")
        assertion_ids = [assertion.assertion_id for assertion in contract.assertions]
        if len(assertion_ids) != len(set(assertion_ids)) or any(
            not item for item in assertion_ids
        ):
            raise ValueError("assertion IDs must be non-empty and unique within a task")
        for assertion in contract.assertions:
            require_standard_fact_path(assertion.path)
            if assertion.operator not in SUPPORTED_OPERATORS:
                raise ValueError(f"unsupported assertion operator: {assertion.operator}")
        state = self._tasks.register(contract)
        contract_ref = self.store.put(contract, prefix="task-contract")
        self._append_event(contract.task_id, "task.created", contract_ref)
        return state

    def observe(self, task_id: str) -> CanonicalSnapshot:
        self._require_task(task_id)
        return self.adopt_snapshot(task_id, self.compositor.observe())

    def adopt_snapshot(self, task_id: str, snapshot: CanonicalSnapshot) -> CanonicalSnapshot:
        """Record a canonical observation captured by an adapter-aware facade."""
        self._require_task(task_id)
        self._tasks.set_snapshot(task_id, snapshot)
        self.store.put(snapshot, object_ref=snapshot.snapshot_id)
        self._append_event(
            task_id,
            "snapshot.created",
            snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            artifact_refs=(snapshot.raw_artifact_ref,) if snapshot.raw_artifact_ref else (),
        )
        return snapshot

    def propose(self, task_id: str, *, strategy: str = "compact") -> ActionProposal:
        if self.proposal_provider is None:
            raise OperationFailure(
                ReasonCode.CAPABILITY_UNAVAILABLE,
                "proposal provider is unavailable",
                retry=False,
                required_action="install-or-configure-provider",
            )
        contract = self._require_task(task_id)
        state = self._tasks.state(task_id)
        snapshot = self._tasks.snapshot(task_id) or self.observe(task_id)
        frame = self.frame_provider.capture_frame() if self.frame_provider is not None else None
        if frame is not None:
            self._tasks.set_frame(task_id, frame)
            self.store.put(frame, object_ref=frame.frame_id)
            self._append_event(
                task_id,
                "frame.captured",
                frame.frame_id,
                caused_by=self._causes_for(snapshot.snapshot_id),
                snapshot_id=snapshot.snapshot_id,
                artifact_refs=(frame.image_ref,),
            )
        context = self.context_builder.build(
            contract,
            state,
            self.ledger.events(task_id),
            based_on_snapshot=snapshot.snapshot_id,
            frame=frame,
            recent_receipt=self._tasks.latest_receipt(task_id),
            assertion_results=self._tasks.recent_results(task_id),
            spatial_projection={
                "snapshot_id": snapshot.snapshot_id,
                "coordinate_space": {
                    "id": snapshot.coordinate_space.id,
                    "bounds": {
                        "x": snapshot.coordinate_space.bounds.x,
                        "y": snapshot.coordinate_space.bounds.y,
                        "width": snapshot.coordinate_space.bounds.width,
                        "height": snapshot.coordinate_space.bounds.height,
                    },
                },
                "active_window": (
                    {
                        "window_id": snapshot.active_window().window_id,
                        "app_id": snapshot.active_window().app_id,
                        "title": snapshot.active_window().title,
                    }
                    if snapshot.active_window() is not None
                    else None
                ),
            },
            primary_attribution=(
                to_primitive(self._audit.primary_attribution(task_id))
                if self._audit.primary_attribution_ref(task_id) is not None
                else None
            ),
            strategy=strategy,
        )
        self.store.put(context, object_ref=context.model_context_id)
        proposal = self.proposal_provider.propose(context)
        if proposal.based_on_snapshot != snapshot.snapshot_id:
            raise ValueError("proposal must reference the current snapshot")
        self.submit_proposal(task_id, proposal, provider_owned=True)
        return proposal

    def submit_proposal(
        self,
        task_id: str,
        proposal: ActionProposal,
        *,
        caused_by: tuple[str, ...] = (),
        provider_owned: bool = False,
    ) -> ActionProposal:
        self._require_task(task_id)
        self._tasks.submit_proposal(task_id, proposal.proposal_id, provider_owned=provider_owned)
        self.store.put(proposal, object_ref=proposal.proposal_id)
        causal_events = caused_by or self._causes_for(proposal.based_on_snapshot)
        if proposal.debug_ref:
            diagnostic = self._append_event(
                task_id,
                "model_diagnostic.recorded",
                proposal.debug_ref,
                caused_by=causal_events,
                snapshot_id=proposal.based_on_snapshot,
                debug_ref=proposal.debug_ref,
            )
            causal_events = (*causal_events, diagnostic.event_id)
        self._append_event(
            task_id,
            "proposal.created",
            proposal.proposal_id,
            caused_by=causal_events,
            snapshot_id=proposal.based_on_snapshot,
            debug_ref=proposal.debug_ref,
        )
        return proposal

    def decide(self, proposal_id: str) -> PolicyDecision:
        task_id = self._tasks.task_for_proposal(proposal_id)
        if task_id is None:
            raise KeyError(proposal_id)
        proposal = self.store.require(proposal_id)
        tags: list[SemanticTag] = []
        for provider in self.policy_providers:
            tags.extend(provider.independent_tags(proposal, self._tasks.contract(task_id)))
        snapshot = self.store.get(proposal.based_on_snapshot)
        if not isinstance(snapshot, CanonicalSnapshot):
            resolution = self.gate.resolve_semantics(proposal, tags)
            decision = PolicyDecision(
                proposal_id=proposal.proposal_id,
                status=PolicyStatus.INVALID,
                reason_code=ReasonCode.SNAPSHOT_UNAVAILABLE,
                semantic_resolution_ref=resolution.semantic_resolution_id,
            )
            guard = None
        else:
            decision, guard, resolution = self.gate.decide(
                proposal, self._tasks.contract(task_id), snapshot, tags
            )
        self.store.put(resolution, object_ref=resolution.semantic_resolution_id)
        if guard is not None:
            self._tasks.record_guard(guard)
            self.store.put(guard, object_ref=guard.guard_id)
        self._store_decision(
            task_id,
            proposal,
            decision,
            caused_by=self._causes_for(proposal_id),
            snapshot_id=(
                snapshot.snapshot_id
                if isinstance(snapshot, CanonicalSnapshot)
                else proposal.based_on_snapshot
            ),
        )
        if decision.status != PolicyStatus.ALLOW:
            self._record_non_execution(task_id, proposal, decision)
        return decision

    def execute(
        self,
        proposal_id: str,
        *,
        confirmed: bool = False,
        current_snapshot: CanonicalSnapshot | None = None,
    ) -> PolicyDecision | ExecutionReceipt:
        # Observation, guard recheck, and input injection are one critical
        # section across tasks; otherwise another task could alter the desktop
        # between validation and the side effect.
        with self._execution_lock:
            return self._execute(
                proposal_id, confirmed=confirmed, current_snapshot=current_snapshot
            )

    def _execute(
        self,
        proposal_id: str,
        *,
        confirmed: bool = False,
        current_snapshot: CanonicalSnapshot | None = None,
    ) -> PolicyDecision | ExecutionReceipt:
        task_id = self._tasks.task_for_proposal(proposal_id)
        if task_id is None:
            raise KeyError(proposal_id)
        existing_receipt = self._tasks.terminal_receipt(proposal_id)
        if existing_receipt is not None:
            return existing_receipt
        proposal: ActionProposal = self.store.require(proposal_id)
        decision = self._tasks.decision(proposal_id) or self.decide(proposal_id)
        if decision.status == PolicyStatus.CONFIRM and confirmed:
            previous_ref = self._tasks.decision_ref(proposal_id)
            if previous_ref is None:
                raise RuntimeError("confirmed proposal has no recorded decision")
            decision = replace(
                decision, status=PolicyStatus.ALLOW, reason_code=ReasonCode.USER_CONFIRMED
            )
            self._store_decision(
                task_id,
                proposal,
                decision,
                caused_by=self._causes_for(previous_ref),
                snapshot_id=proposal.based_on_snapshot,
            )
            self._tasks.update_state(
                task_id, lambda state: replace(state, status=TaskStatus.RUNNING)
            )
        if decision.status != PolicyStatus.ALLOW:
            self._record_non_execution(task_id, proposal, decision)
            return decision

        latest = (
            self.adopt_snapshot(task_id, current_snapshot)
            if current_snapshot is not None
            else self.observe(task_id)
        )
        guard = self._tasks.guard(decision.guard_ref or "")
        if guard is not None:
            guard_error = self.gate.recheck(guard, latest)
            if guard_error is not None:
                stale = replace(decision, status=PolicyStatus.STALE, reason_code=guard_error)
                self._store_decision(
                    task_id,
                    proposal,
                    stale,
                    caused_by=self._causes_for(
                        self._tasks.decision_ref(proposal_id) or proposal_id
                    ),
                    snapshot_id=latest.snapshot_id,
                )
                self._record_non_execution(task_id, proposal, stale)
                return stale

        receipt = self.executor.execute(proposal)
        if (
            receipt.proposal_id != proposal.proposal_id
            or (
                receipt.status == ExecutionStatus.DELIVERED
                and receipt.executed_action != proposal.action
            )
        ):
            receipt = replace(
                receipt,
                proposal_id=proposal.proposal_id,
                status=ExecutionStatus.FAILED,
                error_code=ReasonCode.EXECUTOR_ACTION_MISMATCH,
            )
        self._record_receipt(task_id, receipt)
        if receipt.status == ExecutionStatus.DELIVERED:
            self._tasks.update_state(
                task_id, lambda state: replace(state, step=state.step + 1)
            )
        return receipt

    def evaluate(
        self, task_id: str
    ) -> tuple[tuple[EvidenceRecord, ...], tuple[AssertionResult, ...], TaskState]:
        contract = self._require_task(task_id)
        snapshot = self.observe(task_id)
        evidence: list[EvidenceRecord] = []
        evidence_events: list[str] = []
        for provider in self.evidence_providers:
            try:
                records = provider.collect(contract.assertions, snapshot)
            except Exception as exc:
                self._record_attribution(
                    task_id,
                    AttributionEventKind.ERROR,
                    "evidence-collection",
                    "evidence-provider",
                    ReasonCode.EVIDENCE_COLLECTION_FAILED,
                    f"{provider.provider_id}: {type(exc).__name__}",
                )
                continue
            for record in records:
                if not set(record.facts) <= set(provider.fact_paths):
                    raise ValueError(f"provider emitted undeclared facts: {provider.provider_id}")
                self.store.put(record, object_ref=record.evidence_id)
                event = self._append_event(
                    task_id,
                    "evidence.collected",
                    record.evidence_id,
                    snapshot_id=snapshot.snapshot_id,
                    caused_by=self._latest_execution_causes(task_id),
                    artifact_refs=(record.artifact_ref,) if record.artifact_ref else (),
                )
                evidence_events.append(event.event_id)
                evidence.append(record)
        results = tuple(
            self.evaluator.evaluate(assertion, evidence, snapshot)
            for assertion in contract.assertions
        )
        result_events = []
        for result in results:
            result_ref = self.store.put(result, prefix="assertion-result")
            event = self._append_event(
                task_id,
                "assertion.evaluated",
                result_ref,
                caused_by=tuple(evidence_events),
                snapshot_id=snapshot.snapshot_id,
            )
            result_events.append(event.event_id)
        state = self.reducer.reduce(contract, self._tasks.state(task_id), results)
        self._tasks.set_results(task_id, results)
        self._transactions.state(
            task_id, state, caused_by=tuple(result_events), snapshot_id=snapshot.snapshot_id
        )
        if state.status in {TaskStatus.RETRYING, TaskStatus.FAILED}:
            failed_refs = tuple(
                ref
                for result in results
                if result.status == AssertionStatus.FAILED
                for ref in result.evidence_refs
            )
            self._record_attribution(
                task_id,
                AttributionEventKind.ERROR,
                AttributionStage.OUTCOME,
                AttributionOwner.UNKNOWN,
                (
                    ReasonCode.OUTCOME_POSTCONDITION_FAILED
                    if failed_refs
                    else ReasonCode.ROOT_CAUSE_UNRESOLVED
                ),
                "One or more required task assertions did not pass",
                evidence_refs=failed_refs,
                evidence_status=(
                    AttributionEvidenceStatus.CONFIRMED
                    if failed_refs
                    else AttributionEvidenceStatus.INSUFFICIENT
                ),
            )
        elif any(
            result.status in {AssertionStatus.UNKNOWN, AssertionStatus.CONFLICT}
            for result in results
        ):
            self._record_attribution(
                task_id,
                AttributionEventKind.INSUFFICIENT_EVIDENCE,
                AttributionStage.OUTCOME,
                AttributionOwner.UNKNOWN,
                ReasonCode.INSUFFICIENT_GROUND_TRUTH,
                "Required assertions lack applicable current evidence",
                evidence_status=AttributionEvidenceStatus.INSUFFICIENT,
            )
        return tuple(evidence), results, state

    def run_step(
        self,
        task_id: str,
        *,
        confirmed: bool = False,
        strategy: str = "compact",
    ) -> dict[str, Any]:
        self.observe(task_id)
        proposal = self.propose(task_id, strategy=strategy)
        decision = self.decide(proposal.proposal_id)
        if decision.status not in {PolicyStatus.ALLOW, PolicyStatus.CONFIRM}:
            return {
                "proposal": proposal,
                "decision": decision,
                "receipt": None,
                "state": self._tasks.state(task_id),
            }
        if decision.status == PolicyStatus.CONFIRM and not confirmed:
            return {
                "proposal": proposal,
                "decision": decision,
                "receipt": None,
                "state": self._tasks.state(task_id),
            }
        execution = self.execute(proposal.proposal_id, confirmed=confirmed)
        if isinstance(execution, PolicyDecision):
            return {
                "proposal": proposal,
                "decision": execution,
                "receipt": None,
                "state": self._tasks.state(task_id),
            }
        receipt = execution
        if receipt.status != ExecutionStatus.DELIVERED:
            return {
                "proposal": proposal,
                "decision": decision,
                "receipt": receipt,
                "state": self._tasks.state(task_id),
            }
        evidence, results, state = self.evaluate(task_id)
        return {
            "proposal": proposal,
            "decision": decision,
            "receipt": receipt,
            "evidence": evidence,
            "assertion_results": results,
            "state": state,
        }

    def run(
        self,
        task_id: str,
        *,
        confirmed: bool = False,
        strategy: str = "compact",
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        """Run bounded single-action transactions until the task blocks or terminates."""
        contract = self._require_task(task_id)
        remaining = max(0, contract.limits.max_steps - self._tasks.state(task_id).step)
        limit = remaining if max_iterations is None else min(remaining, max_iterations)
        if limit < 1:
            raise ValueError("no execution iterations remain")
        outcomes: list[dict[str, Any]] = []
        repeated_without_progress = 0
        previous_signature: object = None
        active_strategy = strategy
        for _ in range(limit):
            before = set(self._tasks.state(task_id).completed_assertions)
            outcome = self.run_step(task_id, confirmed=confirmed, strategy=active_strategy)
            proposal = outcome["proposal"]
            decision = outcome["decision"]
            receipt = outcome.get("receipt")
            state = outcome["state"]
            outcomes.append(
                {
                    "proposal_ref": proposal.proposal_id,
                    "decision_ref": self._tasks.decision_ref(proposal.proposal_id),
                    "execution_ref": receipt.execution_id if receipt is not None else None,
                    "task_status": state.status.value,
                }
            )
            if decision.status == PolicyStatus.CONFIRM and not confirmed:
                return {"state": state, "iterations": tuple(outcomes)}
            if decision.status not in {PolicyStatus.ALLOW, PolicyStatus.CONFIRM}:
                return {"state": state, "iterations": tuple(outcomes)}
            if receipt is None or receipt.status != ExecutionStatus.DELIVERED:
                return {"state": state, "iterations": tuple(outcomes)}
            if state.status == TaskStatus.COMPLETED:
                return {"state": state, "iterations": tuple(outcomes)}
            if state.status == TaskStatus.FAILED:
                return {"state": state, "iterations": tuple(outcomes)}

            signature = to_primitive(proposal.action)
            progressed = bool(set(state.completed_assertions) - before)
            if not progressed and signature == previous_signature:
                repeated_without_progress += 1
            else:
                repeated_without_progress = 0
            previous_signature = signature
            if repeated_without_progress >= 1:
                resetter = getattr(self.proposal_provider, "reset", None)
                if callable(resetter):
                    resetter(task_id)
                self._record_attribution(
                    task_id,
                    AttributionEventKind.INCOMPLETE,
                    AttributionStage.PLANNING,
                    AttributionOwner.MODEL,
                    ReasonCode.MODEL_PLANNING_INVALID,
                    "The proposal provider repeated an action without verified progress",
                    evidence_status=AttributionEvidenceStatus.INFERRED,
                )
                return {
                    "state": state,
                    "iterations": tuple(outcomes),
                    "retry": {"retry": False, "required_action": "ask-controller"},
                }
            active_strategy = (
                "recovery" if state.status == TaskStatus.RETRYING else strategy
            )
            if proposal.action.type == ActionType.DONE and state.status != TaskStatus.COMPLETED:
                return {"state": state, "iterations": tuple(outcomes)}
        return {
            "state": self._tasks.state(task_id),
            "iterations": tuple(outcomes),
            "retry": {"retry": True, "required_action": "continue-run"},
        }

    def status(self, task_id: str) -> TaskState:
        self._require_task(task_id)
        return self._tasks.state(task_id)

    def has_task(self, task_id: str) -> bool:
        return self._tasks.has_task(task_id)

    def task_contract(self, task_id: str) -> TaskContract:
        return self._require_task(task_id)

    def latest_snapshot(self, task_id: str) -> CanonicalSnapshot | None:
        self._require_task(task_id)
        return self._tasks.snapshot(task_id)

    def reset(self, task_id: str) -> None:
        with self._execution_lock:
            self._require_task(task_id)
            resetter = getattr(self.proposal_provider, "reset", None)
            if callable(resetter):
                resetter(task_id)
            reset_ref = self.store.put(
                {
                    "task_id": task_id,
                    "previous_state": to_primitive(self._tasks.state(task_id)),
                    "reason": "controller-reset",
                },
                prefix="task-reset",
            )
            self._append_event(
                task_id,
                "task.reset",
                reset_ref,
                caused_by=tuple(event.event_id for event in self.ledger.events(task_id)[-1:]),
            )
            self._tasks.clear_task(task_id)
            self._audit.clear_task(task_id)

    def _require_task(self, task_id: str) -> TaskContract:
        try:
            return self._tasks.contract(task_id)
        except KeyError:
            raise

    def _store_decision(
        self,
        task_id: str,
        proposal: ActionProposal,
        decision: PolicyDecision,
        *,
        caused_by: tuple[str, ...],
        snapshot_id: str,
    ) -> str:
        return self._transactions.decision(
            task_id, proposal, decision, caused_by=caused_by, snapshot_id=snapshot_id
        )

    def _record_non_execution(
        self,
        task_id: str,
        proposal: ActionProposal,
        decision: PolicyDecision,
    ) -> None:
        if not self._tasks.finalized(proposal.proposal_id):
            if not self._transactions.notify_decision(
                self.proposal_provider, task_id, decision
            ):
                self._record_attribution(
                    task_id,
                    AttributionEventKind.ERROR,
                    "protocol",
                    "unknown",
                    ReasonCode.MODEL_PROTOCOL_INVALID,
                    "Proposal provider rejected decision feedback",
                )
            self._tasks.finalize(proposal.proposal_id)
        if decision.status == PolicyStatus.CONFIRM:
            self._tasks.update_state(
                task_id, lambda state: replace(state, status=TaskStatus.NEEDS_CONFIRMATION)
            )
        elif decision.status in {PolicyStatus.DENY, PolicyStatus.INVALID}:
            self._tasks.update_state(
                task_id, lambda state: replace(state, status=TaskStatus.FAILED)
            )
        elif decision.status == PolicyStatus.STALE:
            self._tasks.update_state(
                task_id, lambda state: replace(state, status=TaskStatus.RUNNING)
            )
        reason_code = decision.reason_code
        environment_codes = {
            ReasonCode.COORDINATE_SPACE_CHANGED,
            ReasonCode.TARGET_DISAPPEARED,
            ReasonCode.TARGET_IDENTITY_CHANGED,
            ReasonCode.TARGET_GEOMETRY_INVALIDATED,
            ReasonCode.TARGET_OCCLUDED,
            ReasonCode.HIT_TEST_CHANGED,
            ReasonCode.CURSOR_ORIGIN_CHANGED,
        }
        if reason_code in environment_codes:
            self._record_attribution(
                task_id,
                AttributionEventKind.SAFE_REFUSAL,
                "environment",
                "environment",
                reason_code,
                "Proposal guard detected a relevant environment change",
            )
        elif reason_code in {
            ReasonCode.SEMANTIC_POLICY_DENIED,
            ReasonCode.MECHANICAL_PERMISSION_DENIED,
            ReasonCode.CONFIRMATION_REQUIRED,
        }:
            self._record_attribution(
                task_id,
                AttributionEventKind.POLICY_DECISION,
                "policy",
                "controller-policy",
                (
                    ReasonCode.POLICY_DENIED
                    if reason_code != ReasonCode.CONFIRMATION_REQUIRED
                    else ReasonCode.CONFIRMATION_REQUIRED
                ),
                "Controller policy did not authorize automatic execution",
            )

    def _record_receipt(
        self,
        task_id: str,
        receipt: ExecutionReceipt,
        *,
        terminal: bool = True,
        notify_provider: bool = True,
    ) -> None:
        self._transactions.receipt(
            task_id,
            receipt,
            caused_by=self._causes_for(
                self._tasks.decision_ref(receipt.proposal_id) or receipt.proposal_id
            ),
            terminal=terminal,
        )
        proposal_owner = self._tasks.task_for_proposal(receipt.proposal_id)
        if (
            notify_provider
            and proposal_owner == task_id
            and self._tasks.provider_owns(receipt.proposal_id)
            and not self._tasks.finalized(receipt.proposal_id)
        ):
            if not self._transactions.notify_receipt(self.proposal_provider, task_id, receipt):
                # The receipt remains authoritative. Feedback failure affects
                # only the model adapter's future context and is diagnostic.
                self._record_attribution(
                    task_id,
                    AttributionEventKind.ERROR,
                    "protocol",
                    "unknown",
                    ReasonCode.MODEL_PROTOCOL_INVALID,
                    "Proposal provider rejected execution feedback",
                )
        if receipt.status != ExecutionStatus.DELIVERED:
            self._tasks.update_state(
                task_id, lambda state: replace(state, status=TaskStatus.FAILED)
            )
        if receipt.status == ExecutionStatus.FAILED:
            self._record_attribution(
                task_id,
                AttributionEventKind.ERROR,
                "execution",
                "executor",
                (
                    ReasonCode.EXECUTOR_ACTION_MISMATCH
                    if receipt.error_code == ReasonCode.EXECUTOR_ACTION_MISMATCH
                    else ReasonCode.EXECUTOR_ACTION_FAILED
                ),
                receipt.error_code or "Executor failed to deliver the approved action",
            )

    def _record_attribution(
        self,
        task_id: str,
        event_kind: AttributionEventKind,
        stage: AttributionStage | str,
        owner: AttributionOwner | str,
        code: ReasonCode,
        summary: str,
        *,
        evidence_refs: tuple[str, ...] = (),
        evidence_status: AttributionEvidenceStatus = AttributionEvidenceStatus.CONFIRMED,
    ) -> Attribution:
        return self._audit.record_attribution(
            task_id,
            event_kind,
            stage,
            owner,
            code,
            summary,
            evidence_refs=evidence_refs,
            evidence_status=evidence_status,
        )

    def attributions(self, task_id: str) -> tuple[Attribution, ...]:
        self._require_task(task_id)
        return self._audit.attributions(task_id)

    def primary_attribution(self, task_id: str) -> Attribution | None:
        self._require_task(task_id)
        return self._audit.primary_attribution(task_id)

    def _append_event(self, task_id: str, event_type: str, object_ref: str, **kwargs):
        return self._audit.append(task_id, event_type, object_ref, **kwargs)

    def _causes_for(self, object_ref: str) -> tuple[str, ...]:
        return self._audit.causes_for(object_ref)

    def _latest_execution_causes(self, task_id: str) -> tuple[str, ...]:
        return self._audit.latest_execution_causes(task_id)
