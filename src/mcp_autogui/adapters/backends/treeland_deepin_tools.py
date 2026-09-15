"""Treeland/Deepin implementations behind the stable desktop MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import time
from typing import Any

from ...core.desktop import Point
from ...core.protocol import new_id
from ...core.store import ObjectStore
from ...core.task import AssertionSpec, TaskContract, TaskLimits, TaskPermissions
from ...core.transaction import (
    Action,
    ActionProposal,
    ActionType,
    ExecutionStatus,
    PolicyStatus,
)
from ...desktop_backend import DesktopTransactionRunner, RunBlocking


DEFAULT_APPLICATION_WAIT_TIMEOUT_S = 3.0
MAX_APPLICATION_WAIT_TIMEOUT_S = 30.0
APPLICATION_WAIT_POLL_INTERVAL_S = 0.2


class TreelandDeepinTools:
    """Desktop capabilities contributed by the Treeland/Deepin backend."""

    def __init__(
        self,
        transactions: DesktopTransactionRunner,
        store: ObjectStore,
        run_blocking: RunBlocking,
        *,
        capability_loader: Callable[[], list[dict[str, Any]]],
        capability_resolver: Callable[[str], dict[str, Any] | None],
        application_loader: Callable[[], list[dict[str, Any]]],
        application_validator: Callable[[str], str],
        application_result_for: Callable[[str], object | None],
        read_observation_state: Callable[[], object],
        capture_observation: Callable[[], tuple[bytes, tuple[int, int], object]],
        active_window_summary: Callable[[object], dict[str, object] | None],
    ) -> None:
        self._transactions = transactions
        self._store = store
        self._run_blocking = run_blocking
        self._capability_loader = capability_loader
        self._capability_resolver = capability_resolver
        self._application_loader = application_loader
        self._application_validator = application_validator
        self._application_result_for = application_result_for
        self._read_observation_state = read_observation_state
        self._capture_observation = capture_observation
        self._active_window_summary = active_window_summary

    def list_capabilities(self, category: str = "") -> list[dict[str, Any]]:
        requested_category = category.strip().lower()
        items = self._capability_loader()
        if requested_category:
            items = [
                item for item in items
                if item["category"].lower() == requested_category
            ]
        return items

    async def invoke_shortcut(self, capability_id: str) -> dict[str, Any]:
        resolved_id = capability_id.strip()
        capability = self._capability_resolver(resolved_id)
        if capability is None:
            raise ValueError("unknown desktop capability_id")
        if not capability["enabled"]:
            raise ValueError("desktop capability is disabled in the default schema")
        if not capability["auto_invokable"]:
            raise PermissionError(
                "controller policy does not allow automatic invocation of this capability"
            )
        hotkeys = capability["normalized_hotkeys"]
        if not hotkeys:
            raise ValueError("desktop capability has no keyboard shortcut")
        keys = hotkeys[0]
        task_id = new_id("shortcut-task")
        contract = TaskContract(
            task_id=task_id,
            goal=f"Invoke platform capability {resolved_id}",
            permissions=TaskPermissions(
                frozenset({ActionType.PLATFORM_INVOKE}),
                frozenset({"navigation"}),
            ),
            limits=TaskLimits(max_steps=1, max_retries=0),
        )
        outcome = await self._transactions.execute(
            contract,
            lambda snapshot: ActionProposal(
                proposal_id=new_id("proposal"),
                source="desktop-shortcut",
                based_on_snapshot=snapshot.snapshot_id,
                action=Action(
                    ActionType.PLATFORM_INVOKE,
                    parameters={"capability_id": resolved_id},
                ),
            ),
        )
        raw_before = self._store.require(outcome.snapshot.raw_artifact_ref)
        before = self._active_window_summary(raw_before)
        if outcome.decision.status != PolicyStatus.ALLOW:
            raise PermissionError(
                f"policy refused shortcut: {outcome.decision.reason_code}"
            )
        receipt = outcome.receipt
        if receipt is None or receipt.status != ExecutionStatus.DELIVERED:
            return {
                "status": "failed",
                "capability": capability,
                "executed_keys": [],
                "reason": (
                    receipt.error_code
                    if receipt is not None
                    else outcome.decision.reason_code
                ),
            }
        _, _, post_tree, evidence = await self._run_blocking(
            _capture_post_action_frame,
            self._capture_observation,
            self._read_observation_state,
            self._active_window_summary,
            "",
            0,
        )
        return {
            "status": "success",
            "capability": capability,
            "executed_keys": keys,
            "evidence": {
                "active_window_before": before,
                "active_window_after": self._active_window_summary(post_tree),
                "observation": evidence,
            },
        }

    def list_applications(self, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        needle = query.strip().casefold()
        applications = self._application_loader()
        if needle:
            applications = [
                item for item in applications
                if needle in item["app_id"].casefold()
                or needle in item["display_name"].casefold()
                or needle in (item["display_name_zh_cn"] or "").casefold()
            ]
        return applications[:limit]

    async def launch_application(
        self,
        app_id: str,
        expected_active_app_id: str = "",
        application_wait_timeout_s: float = DEFAULT_APPLICATION_WAIT_TIMEOUT_S,
    ) -> dict[str, Any]:
        resolved_app_id = self._application_validator(app_id)
        expected_app_id = _expected_active_app_id(expected_active_app_id)
        timeout_s = _application_wait_timeout(application_wait_timeout_s)
        task_id = new_id("application-task")
        assertions = (
            (
                AssertionSpec(
                    "application-active",
                    "active_window.app_id",
                    "equals",
                    expected_app_id,
                ),
            )
            if expected_app_id
            else ()
        )
        contract = TaskContract(
            task_id=task_id,
            goal=f"Launch application {resolved_app_id}",
            permissions=TaskPermissions(
                frozenset({ActionType.APPLICATION_LAUNCH}),
                frozenset({"open_application"}),
            ),
            assertions=assertions,
            limits=TaskLimits(max_steps=1, max_retries=0),
            verification_profile="application-open",
        )
        outcome = await self._transactions.execute(
            contract,
            lambda snapshot: ActionProposal(
                proposal_id=new_id("proposal"),
                source="desktop-application-launch",
                based_on_snapshot=snapshot.snapshot_id,
                action=Action(
                    ActionType.APPLICATION_LAUNCH,
                    parameters={"app_id": resolved_app_id},
                ),
                claimed_intent="open_application",
            ),
        )
        active_before = self._active_window_summary(
            self._store.require(outcome.snapshot.raw_artifact_ref)
        )
        if outcome.decision.status != PolicyStatus.ALLOW:
            raise PermissionError(
                f"policy refused application launch: {outcome.decision.reason_code}"
            )
        receipt = outcome.receipt
        result = self._application_result_for(outcome.proposal.proposal_id)
        if receipt is None or receipt.status != ExecutionStatus.DELIVERED:
            return {
                "status": "failed",
                "app_id": resolved_app_id,
                "returncode": getattr(result, "returncode", None),
                "stdout": getattr(result, "stdout", None),
                "stderr": getattr(result, "stderr", None),
                "reason": (
                    receipt.error_code
                    if receipt is not None
                    else outcome.decision.reason_code
                ),
            }

        _, _, post_tree, application_wait = await self._run_blocking(
            _capture_post_action_frame,
            self._capture_observation,
            self._read_observation_state,
            self._active_window_summary,
            expected_app_id,
            timeout_s,
        )
        active_after = self._active_window_summary(post_tree)
        task_validation = _active_app_task_validation(
            expected_app_id,
            active_before,
            active_after,
            application_wait,
        )
        await self._transactions.evaluate(task_id)
        return {
            "status": (
                "success"
                if task_validation is None or task_validation["status"] == "passed"
                else "partial"
            ),
            "app_id": resolved_app_id,
            "returncode": getattr(result, "returncode", 0),
            "stdout": getattr(result, "stdout", ""),
            "stderr": getattr(result, "stderr", ""),
            "evidence": {
                "active_window_before": active_before,
                "active_window_after": active_after,
                "application_wait": application_wait,
            },
            "task_validation": task_validation,
        }


def _expected_active_app_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("expected_active_app_id must be a string")
    return value.strip()


def _application_wait_timeout(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("application_wait_timeout_s must be numeric")
    timeout = float(value)
    if not 0 <= timeout <= MAX_APPLICATION_WAIT_TIMEOUT_S:
        raise ValueError(
            "application_wait_timeout_s must be between 0 and "
            f"{MAX_APPLICATION_WAIT_TIMEOUT_S:g}"
        )
    return timeout


def _capture_post_action_frame(
    capture_frame: Callable[[], tuple[bytes, tuple[int, int], object]],
    read_observation_state: Callable[[], object],
    active_window_summary: Callable[[object], dict[str, object] | None],
    expected_app_id: str,
    timeout_s: float,
) -> tuple[bytes | None, tuple[int, int] | None, object | None, dict[str, Any]]:
    """Poll the lightweight tree, then capture one final post-action frame."""
    started = time.monotonic()
    deadline = started + timeout_s
    attempts = 0
    poll_error = None
    observed_tree = None

    if expected_app_id:
        while True:
            attempts += 1
            try:
                observed_tree = read_observation_state()
                poll_error = None
            except Exception as exc:
                poll_error = f"{type(exc).__name__}: {exc}"

            active_window = (
                active_window_summary(observed_tree)
                if observed_tree is not None
                else None
            )
            actual_app_id = (active_window or {}).get("appId")
            if actual_app_id == expected_app_id:
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(APPLICATION_WAIT_POLL_INTERVAL_S, remaining))

    observation_error = None
    try:
        latest_frame = capture_frame()
    except Exception as exc:
        observation_error = f"{type(exc).__name__}: {exc}"
        latest_frame = (None, None, observed_tree)
    if attempts == 0:
        attempts = 1

    waited_ms = round((time.monotonic() - started) * 1000, 2)
    tree = latest_frame[2]
    active_window = active_window_summary(tree) if tree is not None else None
    actual_app_id = (active_window or {}).get("appId")
    if not expected_app_id:
        status = "not-requested"
    elif actual_app_id == expected_app_id:
        status = "matched"
    elif tree is None:
        status = "observation-unavailable"
    else:
        status = "timeout"
    return (
        latest_frame[0],
        latest_frame[1],
        latest_frame[2],
        {
            "status": status,
            "expected_active_app_id": expected_app_id or None,
            "actual_active_app_id": actual_app_id,
            "attempts": attempts,
            "waited_ms": waited_ms,
            "poll_error": poll_error,
            "observation_error": observation_error,
        },
    )


def _active_app_task_validation(
    expected_app_id: str,
    active_before: dict[str, object] | None,
    active_after: dict[str, object] | None,
    application_wait: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate the lightweight active-app postcondition for one session."""
    if not expected_app_id:
        return None
    before_app_id = (active_before or {}).get("appId")
    actual_app_id = (active_after or {}).get("appId")
    if actual_app_id == expected_app_id:
        status = "passed"
        reason = None
    elif active_after is None:
        status = "unknown"
        reason = "active_window_unavailable"
    elif actual_app_id and actual_app_id != before_app_id:
        status = "failed"
        reason = "wrong_application_active"
    else:
        status = "failed"
        reason = "expected_application_not_observed"
    return {
        "assertion": "active_window.appId == expected_active_app_id",
        "status": status,
        "reason": reason,
        "expected_active_app_id": expected_app_id,
        "actual_active_app_id": actual_app_id,
        "active_window_before": deepcopy(active_before),
        "active_window_after": deepcopy(active_after),
        "attempts": application_wait.get("attempts"),
        "waited_ms": application_wait.get("waited_ms"),
    }
