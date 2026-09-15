"""Compact MCP-facing facade for the v2 core."""

from __future__ import annotations

from typing import Any

from .core.desktop import Point
from .core.protocol import ProtocolFailure, ReasonCode, new_id, to_primitive
from .core.task import AssertionSpec, TaskContract, TaskLimits, TaskPermissions, TaskStatus
from .core.transaction import (
    Action,
    ActionProposal,
    ActionType,
    ExecutionReceipt,
    ExecutionStatus,
    PolicyDecision,
    PolicyStatus,
)
from .core.orchestrator import CoreOrchestrator
from .public_response import reduce_public_response, response_envelope


_ACTION_ALIASES = {
    "keyboard.text_input": "keyboard.text",
    "keyboard.keys": "keyboard.key",
    "keyboard.shortcuts": "keyboard.shortcut",
}
_PUBLIC_OPERATIONS = frozenset({"describe", "run", "status", "confirm", "reset"})
_DIAGNOSTIC_OPERATIONS = frozenset({"describe", "observe", "propose", "decide", "execute", "evaluate", "trace"})


class GuiRunFacade:
    def __init__(
        self,
        runtime: CoreOrchestrator,
        *,
        effective_config: dict[str, Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.effective_config = effective_config

    def handle(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        """Handle the compact task-lifecycle API."""
        normalized = _normalize_operation(operation)
        if normalized not in _PUBLIC_OPERATIONS:
            return self._public_failure(
                normalized,
                ReasonCode.UNSUPPORTED_OPERATION,
                "unsupported public gui_run operation; use gui_diagnostic for controller internals",
                "call-run-status-confirm-or-reset",
            )
        try:
            return self._handle_public(normalized, **kwargs)
        except KeyError as exc:
            return self._public_failure(
                normalized, ReasonCode.OBJECT_NOT_FOUND, str(exc), "describe-or-create-task"
            )
        except ProtocolFailure as exc:
            return self._public_failure(
                normalized,
                exc.reason_code,
                str(exc),
                exc.required_action,
                retry=exc.retry,
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            return self._public_failure(
                normalized,
                ReasonCode.CONTROLLER_TASK_CONTRACT_INVALID,
                str(exc),
                "correct-request",
            )

    def handle_diagnostic(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        """Handle explicit controller diagnostics without reducing their facts."""
        normalized = _normalize_operation(operation)
        if normalized not in _DIAGNOSTIC_OPERATIONS:
            return response_envelope(
                normalized,
                "failed",
                error={
                    "code": ReasonCode.UNSUPPORTED_OPERATION,
                    "message": "unsupported gui_diagnostic operation",
                    "retry": False,
                    "required_action": "call-describe-observe-propose-decide-execute-evaluate-or-trace",
                },
            )
        try:
            return self._handle_diagnostic(normalized, **kwargs)
        except KeyError as exc:
            return response_envelope(
                normalized, "failed", error={"code": ReasonCode.OBJECT_NOT_FOUND, "message": str(exc)}
            )
        except ProtocolFailure as exc:
            return response_envelope(
                normalized,
                "failed",
                error={
                    "code": exc.reason_code,
                    "message": str(exc),
                    "retry": exc.retry,
                    "required_action": exc.required_action,
                },
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            return response_envelope(
                normalized,
                "failed",
                error={"code": ReasonCode.CONTROLLER_TASK_CONTRACT_INVALID, "message": str(exc)},
            )

    def _handle_public(
        self,
        operation: str,
        *,
        task_id: str = "",
        task_contract: dict[str, Any] | None = None,
        proposal_id: str = "",
        confirmed: bool = False,
        strategy: str = "compact",
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        if operation == "describe":
            return reduce_public_response(
                operation,
                task_state=None,
                object_ref=self._store_description(),
            )

        resolved_task = self._prepare_task(task_id, task_contract)
        if operation == "confirm":
            value = self.runtime.execute(proposal_id.strip(), confirmed=True)
            if isinstance(value, PolicyDecision):
                ref = self._last_object_ref(resolved_task, "decision.created")
                error = retry = None
            else:
                ref = value.execution_id
                error, retry = _execution_failure(value)
            return reduce_public_response(
                operation,
                task_state=self.runtime.status(resolved_task).status.value,
                object_ref=ref,
                error=error,
                retry=retry,
            )
        if operation == "run":
            value = self.runtime.run(
                resolved_task,
                confirmed=confirmed,
                strategy=strategy,
                max_iterations=max_iterations,
            )
            ref = self.runtime.store.put(value, prefix="run-result")
            return reduce_public_response(
                operation,
                task_state=value["state"].status.value,
                object_ref=ref,
                retry=value.get("retry"),
            )
        if operation == "status":
            state = self.runtime.status(resolved_task)
            ref = self.runtime.store.put(state, prefix="task-state")
            return reduce_public_response(
                operation,
                task_state=state.status.value,
                object_ref=ref,
            )
        if operation == "reset":
            self.runtime.reset(resolved_task)
            return reduce_public_response(operation, task_state=None)
        raise ValueError(f"unsupported gui_run operation: {operation}")

    def _handle_diagnostic(
        self,
        operation: str,
        *,
        task_id: str = "",
        task_contract: dict[str, Any] | None = None,
        proposal: dict[str, Any] | None = None,
        proposal_id: str = "",
        confirmed: bool = False,
        strategy: str = "compact",
        object_ref: str = "",
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        if operation == "describe":
            return self._diagnostic_response(
                operation,
                "ok",
                self._store_description(),
            )
        if operation == "trace" and object_ref:
            value = self.runtime.store.require(object_ref)
            expanded = (
                {"type": "binary-artifact", "size": len(value)}
                if isinstance(value, bytes)
                else to_primitive(value)
            )
            return {
                "protocol_version": 2,
                "operation": "trace",
                "status": "ok",
                "object_ref": object_ref,
                "object": expanded,
            }

        resolved_task = self._prepare_task(task_id, task_contract)
        if operation == "observe":
            value = self.runtime.observe(resolved_task)
            return self._diagnostic_response(
                operation, "ok", value.snapshot_id, resolved_task
            )
        if operation == "propose":
            if proposal is None:
                value = self.runtime.propose(resolved_task, strategy=strategy)
            else:
                current = (
                    self.runtime.latest_snapshot(resolved_task)
                    or self.runtime.observe(resolved_task)
                )
                value = self.runtime.submit_proposal(
                    resolved_task,
                    parse_action_proposal(proposal, current.snapshot_id),
                )
            return self._diagnostic_response(
                operation,
                TaskStatus.RUNNING.value,
                value.proposal_id,
                resolved_task,
            )
        if operation == "decide":
            value = self.runtime.decide(proposal_id.strip())
            ref = self._last_object_ref(resolved_task, "decision.created")
            return self._diagnostic_response(
                operation,
                _diagnostic_decision_status(value.status),
                ref,
                resolved_task,
            )
        if operation == "execute":
            value = self.runtime.execute(proposal_id.strip(), confirmed=confirmed)
            if isinstance(value, PolicyDecision):
                ref = self._last_object_ref(resolved_task, "decision.created")
                return self._diagnostic_response(
                    operation,
                    _diagnostic_decision_status(value.status),
                    ref,
                    resolved_task,
                )
            response = self._diagnostic_response(
                operation,
                _diagnostic_receipt_status(value),
                value.execution_id,
                resolved_task,
            )
            error, retry = _execution_failure(value)
            if error is not None:
                response["error"] = error
                response["retry"] = retry
            return response
        if operation == "evaluate":
            _, _, state = self.runtime.evaluate(resolved_task)
            ref = self._last_object_ref(resolved_task, "task.transitioned")
            return self._diagnostic_response(
                operation,
                state.status.value,
                ref,
                resolved_task,
            )
        if operation == "trace":
            return {
                "protocol_version": 2,
                "operation": "trace",
                "status": "ok",
                "events": [
                    to_primitive(item)
                    for item in self.runtime.ledger.events(resolved_task)
                ],
                "attributions": [
                    to_primitive(item)
                    for item in self.runtime.attributions(resolved_task)
                ],
            }
        raise ValueError(f"unsupported gui_diagnostic operation: {operation}")

    def _prepare_task(
        self,
        task_id: str,
        task_contract: dict[str, Any] | None,
    ) -> str:
        resolved_task = (
            task_id.strip()
            or str((task_contract or {}).get("task_id") or "").strip()
        )
        if not resolved_task:
            raise ValueError("task_id is required")
        if task_contract is None:
            return resolved_task
        parsed_contract = parse_task_contract(task_contract)
        if parsed_contract.task_id != resolved_task:
            raise ValueError("task_id does not match task_contract.task_id")
        if self.runtime.has_task(resolved_task):
            if self.runtime.task_contract(resolved_task) != parsed_contract:
                raise ValueError("task_contract cannot change after task creation")
        else:
            self.runtime.register_task(parsed_contract)
        return resolved_task

    def _store_description(self) -> str:
        description = {
            "protocol_version": 2,
            "schema_version": "1",
            "schema_revision": "2.1-p4",
            "adapter": to_primitive(self.runtime.compositor.descriptor),
            "capabilities": {
                "pointer": self.runtime.executor is not None,
                "keyboard": self.runtime.executor is not None,
                "window_geometry": (
                    self.runtime.compositor.descriptor.capabilities.desktop_geometry
                ),
                "frame": self.runtime.frame_provider is not None,
                "child_control_semantics": (
                    self.runtime.compositor.descriptor.capabilities.child_controls
                ),
            },
            "providers": {
                "proposal": _component_id(
                    self.runtime.proposal_provider, "provider_id"
                ),
                "frame": _component_id(self.runtime.frame_provider, "provider_id"),
                "policy": [
                    _component_id(item, "provider_id")
                    for item in self.runtime.policy_providers
                ],
                "evidence": [
                    {
                        "provider_id": item.provider_id,
                        "fact_paths": sorted(item.fact_paths),
                    }
                    for item in self.runtime.evidence_providers
                ],
                "executor": _component_id(self.runtime.executor, "executor_id"),
            },
            "actions": [item.value for item in ActionType],
            "operations": sorted(_PUBLIC_OPERATIONS),
            "diagnostic_operations": sorted(_DIAGNOSTIC_OPERATIONS),
            "context_strategies": sorted(self.runtime.context_builder.STRATEGIES),
            "policy_profiles": sorted(self.runtime.gate.policy_profiles),
        }
        if self.effective_config is not None:
            description["effective_config"] = self.effective_config
        return self.runtime.store.put(description, prefix="description")

    def _diagnostic_response(
        self,
        operation: str,
        status: str,
        ref: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        response = response_envelope(operation, status, object_ref=ref)
        response["task_id"] = task_id
        response["task_state"] = (
            self.runtime.status(task_id).status.value if task_id is not None else None
        )
        response["object"] = to_primitive(self.runtime.store.require(ref))
        if task_id is not None:
            response["attribution_refs"] = [
                item.attribution_id for item in self.runtime.attributions(task_id)
            ]
        return response

    @staticmethod
    def _public_failure(
        operation: str, code: ReasonCode, message: str, required_action: str, *, retry: bool = False
    ) -> dict[str, Any]:
        return reduce_public_response(
            operation,
            task_state=None,
            error={"code": code, "message": message, "retry": retry, "required_action": required_action},
        )

    def _last_object_ref(self, task_id: str, event_type: str) -> str:
        return next(
            event.object_ref
            for event in reversed(self.runtime.ledger.events(task_id))
            if event.event_type == event_type
        )


def _diagnostic_decision_status(status: PolicyStatus) -> str:
    return {
        PolicyStatus.ALLOW: TaskStatus.RUNNING.value,
        PolicyStatus.CONFIRM: TaskStatus.NEEDS_CONFIRMATION.value,
        PolicyStatus.DENY: TaskStatus.FAILED.value,
        PolicyStatus.INVALID: TaskStatus.FAILED.value,
        PolicyStatus.STALE: TaskStatus.RUNNING.value,
    }[status]


def _diagnostic_receipt_status(receipt: ExecutionReceipt) -> str:
    if receipt.error_code == ReasonCode.CONFIRMATION_REQUIRED:
        return TaskStatus.NEEDS_CONFIRMATION.value
    if receipt.status == ExecutionStatus.DELIVERED:
        return TaskStatus.RUNNING.value
    return TaskStatus.FAILED.value


def _execution_failure(
    receipt: ExecutionReceipt,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if receipt.error_code is None or receipt.error_code == ReasonCode.CONFIRMATION_REQUIRED:
        return None, None
    recovery = _recovery_for(receipt.error_code)
    return (
        {
            "code": receipt.error_code,
            "message": "The proposed action was not delivered",
            **recovery,
        },
        recovery,
    )


def parse_task_contract(value: dict[str, Any]) -> TaskContract:
    if not isinstance(value, dict):
        raise ValueError("task_contract must be an object")
    permissions = value.get("permissions") or {}
    actions = frozenset(
        ActionType(_ACTION_ALIASES.get(str(item), str(item)))
        for item in permissions.get("actions", [])
    )
    assertions = tuple(
        AssertionSpec(
            assertion_id=str(item["assertion_id"]),
            path=str(item["path"]),
            operator=str(item["operator"]),
            expected=item.get("expected"),
            required=bool(item.get("required", True)),
            recoverable=bool(item.get("recoverable", True)),
            subject=dict(item.get("subject") or {}),
            providers=tuple(str(provider) for provider in item.get("providers", [])),
        )
        for item in value.get("assertions", [])
    )
    limits = value.get("limits") or {}
    return TaskContract(
        task_id=str(value.get("task_id") or "").strip(),
        goal=str(value.get("goal") or "").strip(),
        permissions=TaskPermissions(
            actions,
            frozenset(str(item) for item in permissions.get("semantic_intents", [])),
        ),
        assertions=assertions,
        limits=TaskLimits(int(limits.get("max_steps", 10)), int(limits.get("max_retries", 1))),
        policy_profile=str(value.get("policy_profile") or "desktop-safe-default"),
        verification_profile=str(value.get("verification_profile") or "default"),
        policy_overrides=dict(value.get("policy_overrides") or {}),
    )


def _component_id(component: Any, attribute: str) -> str | None:
    if component is None:
        return None
    return str(getattr(component, attribute, type(component).__name__))


def _normalize_operation(operation: str) -> str:
    return {"assess": "decide", "verify": "evaluate"}.get(operation.strip().lower(), operation.strip().lower())


def _recovery_for(code: ReasonCode) -> dict[str, Any]:
    if code in {
        ReasonCode.COORDINATE_SPACE_CHANGED,
        ReasonCode.TARGET_DISAPPEARED,
        ReasonCode.TARGET_IDENTITY_CHANGED,
        ReasonCode.TARGET_GEOMETRY_INVALIDATED,
        ReasonCode.TARGET_OCCLUDED,
        ReasonCode.HIT_TEST_CHANGED,
        ReasonCode.CURSOR_ORIGIN_CHANGED,
    }:
        return {"retry": True, "required_action": "capture-new-frame"}
    if code == ReasonCode.CAPABILITY_UNAVAILABLE:
        return {"retry": False, "required_action": "install-or-configure-provider"}
    if code in {ReasonCode.MECHANICAL_PERMISSION_DENIED, ReasonCode.SEMANTIC_POLICY_DENIED}:
        return {"retry": False, "required_action": "review-task-policy"}
    return {"retry": True, "required_action": "retry-execution"}


def parse_action_proposal(value: dict[str, Any], default_snapshot: str) -> ActionProposal:
    if not isinstance(value, dict):
        raise ValueError("proposal must be an object")
    action_value = value.get("action") or {}
    action_type = ActionType(_ACTION_ALIASES.get(str(action_value.get("type")), str(action_value.get("type"))))
    coordinate_value = action_value.get("coordinate")
    point = None
    space = None
    if coordinate_value is not None:
        if not isinstance(coordinate_value, dict):
            raise ValueError("action.coordinate must be an object")
        point = Point(float(coordinate_value["x"]), float(coordinate_value["y"]))
        space = str(coordinate_value.get("space") or action_value.get("coordinate_space") or "")
    parameters = dict(action_value.get("parameters") or {})
    for key, item in action_value.items():
        if key not in {"type", "coordinate", "coordinate_space", "parameters"}:
            parameters.setdefault(key, item)
    claimed_intent = value.get("claimed_intent")
    if "semantic_intent" in value:
        raise ValueError("semantic_intent is not supported; use claimed_intent")
    if "expected_effect" in value:
        raise ValueError("expected_effect is not supported; define completion with task assertions")
    return ActionProposal(
        proposal_id=str(value.get("proposal_id") or new_id("proposal")),
        source=str(value.get("source") or "controller"),
        based_on_snapshot=str(value.get("based_on_snapshot") or default_snapshot),
        action=Action(action_type, point, space, parameters),
        claimed_intent=claimed_intent,
        debug_ref=value.get("debug_ref"),
    )
