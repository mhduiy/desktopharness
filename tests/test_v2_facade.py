import unittest
from unittest.mock import patch

from mcp_autogui.core.models import (
    ActionType,
    AdapterCapabilities,
    AdapterDescriptor,
    CanonicalSnapshot,
    CanonicalWindowFact,
    CoordinateSpace,
    ExecutionReceipt,
    ExecutionStatus,
    FrameReference,
    OutputFact,
    Point,
    PolicyDecision,
    PolicyStatus,
    OperationFailure,
    ReasonCode,
    Rect,
    StackingCapabilities,
    StackingModel,
    TaskStatus,
    WindowRole,
    new_id,
    utc_now,
)
from mcp_autogui.core.orchestrator import CoreOrchestrator
from mcp_autogui.core.store import ObjectStore
from mcp_autogui.facade import AutoUIFacade, parse_action_proposal
from mcp_autogui.adapters.proposal.qwen_cua import QwenCUAProposalProvider, QwenProposalError
from mcp_autogui.runtime_description import RuntimeDescription


class Compositor:
    descriptor = AdapterDescriptor(
        "portable-fixture",
        AdapterCapabilities(
            True, True, True,
            StackingCapabilities(StackingModel.HIT_TEST, hit_test=True),
            active_window=True,
            window_identity="stable",
        ),
    )

    def __init__(self):
        self.number = 0

    def observe(self):
        self.number += 1
        bounds = Rect(0, 0, 1000, 800)
        return CanonicalSnapshot(
            f"snapshot-{self.number}", utc_now(), "same-environment",
            CoordinateSpace("desktop-logical", bounds, "geometry-1"),
            (OutputFact("display", bounds),), Point(5, 5),
            (CanonicalWindowFact("desktop", bounds, app_id="desktop", visible=True, active=True, role=WindowRole.DESKTOP),),
        )

    def hit_test(self, point, snapshot=None):
        return "desktop"


class Executor:
    def execute(self, proposal):
        now = utc_now()
        return ExecutionReceipt(new_id("execution"), proposal.proposal_id, ExecutionStatus.DELIVERED, proposal.action, now, now)


class FailingExecutor:
    def execute(self, proposal):
        now = utc_now()
        return ExecutionReceipt(
            new_id("execution"),
            proposal.proposal_id,
            ExecutionStatus.FAILED,
            None,
            now,
            now,
            ReasonCode.EXECUTOR_ACTION_FAILED,
        )


class ProposalProvider:
    provider_id = "fixture-proposal"

    def propose(self, context):
        from mcp_autogui.core.models import Action, ActionProposal, ActionType

        return ActionProposal(
            new_id("proposal"),
            self.provider_id,
            context.based_on_snapshot,
            Action(ActionType.POINTER_CLICK, Point(100, 100), "desktop-logical"),
        )


def runtime_description_for(runtime, effective_config=None):
    return RuntimeDescription.from_components(
        compositor=runtime.compositor,
        executor=runtime.executor,
        proposal_provider=runtime.proposal_provider,
        frame_provider=runtime.frame_provider,
        policy_providers=runtime.policy_providers,
        evidence_providers=runtime.evidence_providers,
        policy_profiles=runtime.gate.policy_profiles,
        context_strategies=runtime.context_builder.STRATEGIES,
        effective_config=effective_config,
    )


def facade_for(runtime):
    return AutoUIFacade(runtime, runtime_description_for(runtime))


class PolicyProvider:
    provider_id = "fixture-policy"

    def independent_tags(self, proposal, contract):
        from mcp_autogui.core.models import EvidenceConfidence, SemanticTag

        return [SemanticTag("navigation", self.provider_id, None, EvidenceConfidence.DETERMINISTIC)]


TASK = {
    "task_id": "portable-task",
    "goal": "click a visual target",
    "permissions": {
        "actions": ["pointer.click"],
        "semantic_intents": ["navigation"],
    },
    "assertions": [],
    "limits": {"max_steps": 2, "max_retries": 0},
    "policy_profile": "desktop-safe-default",
}


class FacadeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = CoreOrchestrator(Compositor(), Executor())
        self.facade = facade_for(self.runtime)

    def test_describe_exposes_capabilities_separately_from_task_permissions(self):
        public = self.facade.handle("describe")
        response = self.facade.handle_diagnostic("describe")

        self.assertEqual(public["status"], "completed")
        self.assertNotIn("object", public)
        self.assertEqual(response["protocol_version"], 2)
        self.assertEqual(response["object"]["schema_revision"], "2.1-p6")
        self.assertEqual(response["object"]["proposal_model"]["actions"], "ordered-sequence")
        self.assertEqual(response["object"]["adapter"]["adapter_id"], "portable-fixture")
        self.assertIn("pointer.click", response["object"]["actions"])
        self.assertEqual(response["object"]["operations"], ["confirm", "describe", "reset", "run", "status"])

    def test_runtime_description_is_an_immutable_snapshot(self):
        effective_config = {"transport": {"port": 8651}}
        description = runtime_description_for(self.runtime, effective_config)

        effective_config["transport"]["port"] = 9999
        first_read = description.to_dict()
        first_read["capabilities"]["pointer"] = False

        second_read = description.to_dict()
        self.assertEqual(second_read["effective_config"]["transport"]["port"], 8651)
        self.assertTrue(second_read["capabilities"]["pointer"])

    def test_compact_operations_return_references_and_trace_expands_them(self):
        observed = self.facade.handle_diagnostic("observe", task_contract=TASK)
        proposed = self.facade.handle_diagnostic(
            "propose",
            task_id="portable-task",
            proposal={
                "source": "controller",
                "based_on_snapshot": observed["object_ref"],
                "action": {
                    "type": "pointer.click",
                    "coordinate": {"space": "desktop-logical", "x": 100, "y": 100},
                },
                "claimed_intent": "navigation",
            },
        )
        decided = self.facade.handle_diagnostic(
            "decide", task_id="portable-task", proposal_id=proposed["object_ref"]
        )

        self.assertEqual(proposed["status"], "running")
        self.assertEqual(proposed["task_state"], "running")
        self.assertIn("attribution_refs", proposed)
        # Controller intent is still a claim without independent semantic evidence.
        self.assertEqual(decided["status"], "needs-confirmation")
        expanded = self.facade.handle_diagnostic(
            "trace", task_id="portable-task", object_ref=proposed["object_ref"]
        )
        self.assertEqual(expanded["object"]["action"]["type"], "pointer.click")

        pending = self.facade.handle_diagnostic(
            "execute", task_id="portable-task", proposal_id=proposed["object_ref"]
        )
        delivered = self.facade.handle(
            "confirm", task_id="portable-task", proposal_id=proposed["object_ref"]
        )
        repeated = self.facade.handle(
            "confirm", task_id="portable-task", proposal_id=proposed["object_ref"]
        )
        self.assertEqual(pending["status"], "needs-confirmation")
        self.assertTrue(pending["object_ref"].startswith("policy-decision-"))
        self.assertEqual(delivered["status"], "running")
        self.assertEqual(repeated["object_ref"], delivered["object_ref"])

    def test_task_trace_remains_available_after_reset(self):
        self.facade.handle_diagnostic("observe", task_contract=TASK)
        reset = self.facade.handle("reset", task_id="portable-task")

        traced = self.facade.handle_diagnostic(
            "trace", task_id="portable-task"
        )

        self.assertEqual(reset["status"], "completed")
        self.assertEqual(traced["status"], "ok")
        self.assertEqual(traced["events"][-1]["event_type"], "task.reset")

    def test_task_trace_rejects_a_truly_unknown_task(self):
        response = self.facade.handle_diagnostic(
            "trace", task_id="never-created"
        )

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["error"]["code"], ReasonCode.OBJECT_NOT_FOUND)

    def test_stale_guard_response_requests_a_new_frame(self):
        self.facade.handle_diagnostic("observe", task_contract=TASK)
        decision = PolicyDecision(
            proposal_id="proposal-stale",
            status=PolicyStatus.STALE,
            reason_code=ReasonCode.HIT_TEST_CHANGED,
        )
        self.runtime.store.put(decision, object_ref="decision-stale")
        self.runtime.ledger.append("portable-task", "decision.created", "decision-stale")
        with patch.object(self.runtime, "execute", return_value=decision):
            response = self.facade.handle_diagnostic(
                "execute", task_id="portable-task", proposal_id="proposal-stale"
            )

        self.assertEqual(response["status"], "running")
        self.assertEqual(response["error"]["code"], ReasonCode.HIT_TEST_CHANGED)
        self.assertEqual(response["error"]["required_action"], "capture-new-frame")
        self.assertTrue(response["retry"]["retry"])

    def test_diagnostics_use_attribution_event_refs_not_deserialized_objects(self):
        self.runtime.ledger.append(
            "portable-task", "attribution.recorded", "attribution-persisted"
        )
        with patch.object(
            self.runtime,
            "attributions",
            side_effect=AttributeError("persisted attribution is a dict"),
        ):
            response = self.facade.handle_diagnostic("observe", task_contract=TASK)

        self.assertEqual(response["attribution_refs"], ["attribution-persisted"])

    def test_run_exposes_the_bounded_automatic_transaction_loop(self):
        runtime = CoreOrchestrator(
            Compositor(),
            Executor(),
            proposal_provider=ProposalProvider(),
            policy_providers=(PolicyProvider(),),
        )
        facade = facade_for(runtime)
        response = facade.handle("run", task_contract=TASK, max_iterations=1)

        self.assertEqual(response["status"], "running")
        self.assertNotIn("object", response)
        self.assertEqual(response["retry"]["required_action"], "continue-run")

    def test_execution_failure_is_recorded_in_task_state(self):
        runtime = CoreOrchestrator(
            Compositor(),
            FailingExecutor(),
            proposal_provider=ProposalProvider(),
            policy_providers=(PolicyProvider(),),
        )
        facade = facade_for(runtime)

        response = facade.handle("run", task_contract=TASK, max_iterations=1)
        stored_result = runtime.store.require(response["object_ref"])

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["task_state"], "failed")
        self.assertNotIn("status", stored_result)
        self.assertEqual(stored_result["state"].status, TaskStatus.FAILED)

    def test_public_operations_reject_controller_stage_operations(self):
        response = self.facade.handle("observe", task_contract=TASK)

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["error"]["code"], ReasonCode.UNSUPPORTED_OPERATION)

    def test_typed_protocol_failure_controls_public_recovery(self):
        failure = OperationFailure(
            ReasonCode.CAPABILITY_UNAVAILABLE,
            "message text is not part of classification",
            retry=False,
            required_action="install-or-configure-provider",
        )
        with patch.object(self.facade, "_handle_public", side_effect=failure):
            response = self.facade.handle("describe")

        self.assertEqual(response["error"]["code"], ReasonCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(response["error"]["required_action"], "install-or-configure-provider")

    def test_untyped_exception_text_does_not_change_reason_code(self):
        with patch.object(
            self.facade,
            "_handle_public",
            side_effect=RuntimeError(ReasonCode.SNAPSHOT_UNAVAILABLE),
        ):
            response = self.facade.handle("describe")

        self.assertEqual(
            response["error"]["code"],
            ReasonCode.CONTROLLER_TASK_CONTRACT_INVALID,
        )

    def test_legacy_proposal_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "semantic_intent"):
            parse_action_proposal(
                {
                    "semantic_intent": "navigation",
                    "action": {"type": "done"},
                },
                "snapshot-1",
            )
        with self.assertRaisesRegex(ValueError, "expected_effect"):
            parse_action_proposal(
                {
                    "expected_effect": {"opened": True},
                    "action": {"type": "done"},
                },
                "snapshot-1",
            )

    def test_manual_proposal_accepts_an_ordered_action_sequence(self):
        proposal = parse_action_proposal(
            {
                "source": "controller",
                "actions": [
                    {
                        "type": "pointer.move",
                        "coordinate": {"x": 100, "y": 100, "space": "desktop-logical"},
                    },
                    {"type": "pointer.scroll", "parameters": {"clicks": -3}},
                ],
            },
            "snapshot-1",
        )

        self.assertEqual(
            [action.type.value for action in proposal.action_sequence],
            ["pointer.move", "pointer.scroll"],
        )


class Backend:
    def __init__(self, actions):
        self.actions = actions

    def predict(self, *args, **kwargs):
        return {"actions": self.actions, "observation_text": "claim"}


class QwenProposalAdapterTests(unittest.TestCase):
    def context_and_store(self):
        from mcp_autogui.core.models import ModelContext

        store = ObjectStore()
        bounds = Rect(-100, 0, 2000, 1000)
        snap = CanonicalSnapshot(
            "snapshot-q", utc_now(), "env", CoordinateSpace("desktop-logical", bounds),
            (OutputFact("display", bounds),), None, (),
        )
        store.put(snap, object_ref=snap.snapshot_id)
        store.put(b"png", object_ref="image-q")
        frame = FrameReference("frame-q", utc_now(), "image-q", (1000, 500))
        context = ModelContext(
            "context-q", "task-q", "snapshot-q", frame, "click", 0, (), (), None, (),
            {"ordered_action_sequence": True}, (),
        )
        return context, store

    def test_qwen_coordinate_is_mapped_to_desktop_logical_space(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(Backend(["pyautogui.click(500, 250)"]), store)
        proposal = provider.propose(context)
        self.assertEqual(proposal.action.coordinate, Point(900, 500))
        self.assertEqual(proposal.action.coordinate_space, "desktop-logical")

    def test_qwen_multiple_actions_form_one_ordered_proposal(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(
            Backend(["pyautogui.click(1, 1)", "pyautogui.click(2, 2)"]), store
        )
        proposal = provider.propose(context)
        self.assertEqual(len(proposal.action_sequence), 2)
        self.assertEqual(
            [action.coordinate for action in proposal.action_sequence],
            [Point(-98, 2), Point(-96, 4)],
        )

    def test_qwen_preserves_a_granular_drag_as_one_proposal(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(
            Backend([
                "pyautogui.moveTo(100, 100)",
                "pyautogui.mouseDown()",
                "pyautogui.moveTo(300, 200)",
                "pyautogui.mouseUp()",
            ]),
            store,
        )

        proposal = provider.propose(context)

        self.assertEqual(
            [action.type for action in proposal.action_sequence],
            [
                ActionType.POINTER_MOVE,
                ActionType.POINTER_CLICK,
                ActionType.POINTER_MOVE,
                ActionType.POINTER_CLICK,
            ],
        )
        self.assertEqual(
            [action.parameters.get("event") for action in proposal.action_sequence],
            [None, "down", None, "up"],
        )
        self.assertEqual(
            [action.coordinate for action in proposal.action_sequence],
            [Point(100, 200), Point(100, 200), Point(500, 400), Point(500, 400)],
        )

    def test_unsupported_qwen_action_retains_raw_model_output(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(Backend(["WAIT"]), store)

        with self.assertRaises(QwenProposalError) as caught:
            provider.propose(context)

        self.assertEqual(store.require(caught.exception.debug_ref)["actions"], ["WAIT"])

    def test_qwen_decision_feedback_clears_pending_without_a_receipt(self):
        calls = []

        class FeedbackBackend:
            def record_execution(self, *args, **kwargs):
                calls.append((args, kwargs))
                return {"ok": True}

        _, store = self.context_and_store()
        provider = QwenCUAProposalProvider(FeedbackBackend(), store)
        provider.record_decision(
            "task-q",
            PolicyDecision(
                proposal_id="proposal-q",
                status=PolicyStatus.CONFIRM,
                reason_code=ReasonCode.CONFIRMATION_REQUIRED,
            ),
        )

        self.assertEqual(calls[0][0], ("task-q",))
        self.assertEqual(calls[0][1]["status"], "partial")
        self.assertEqual(calls[0][1]["execution"]["status"], "confirm")


if __name__ == "__main__":
    unittest.main()
