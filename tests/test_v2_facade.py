import unittest

from mcp_autogui.core.models import (
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
    ReasonCode,
    Rect,
    StackingCapabilities,
    StackingModel,
    WindowRole,
    new_id,
    utc_now,
)
from mcp_autogui.core.orchestrator import CoreOrchestrator
from mcp_autogui.core.store import ObjectStore
from mcp_autogui.facade import GuiRunFacade, parse_action_proposal
from mcp_autogui.adapters.proposal.qwen_cua import QwenCUAProposalProvider


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
        self.facade = GuiRunFacade(self.runtime)

    def test_describe_exposes_capabilities_separately_from_task_permissions(self):
        response = self.facade.handle("describe", diagnostic=True)
        self.assertEqual(response["protocol_version"], 2)
        self.assertEqual(response["object"]["schema_revision"], "2.1-p3")
        self.assertEqual(response["object"]["adapter"]["adapter_id"], "portable-fixture")
        self.assertIn("pointer.click", response["object"]["actions"])
        self.assertEqual(response["object"]["recommended_operations"], ["run", "status", "confirm", "reset"])

    def test_compact_operations_return_references_and_trace_expands_them(self):
        observed = self.facade.handle("observe", task_contract=TASK)
        proposed = self.facade.handle(
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
        decided = self.facade.handle(
            "decide", task_id="portable-task", proposal_id=proposed["object_ref"]
        )

        self.assertEqual(proposed["status"], "running")
        self.assertEqual(proposed["task_state"], "running")
        self.assertNotIn("attribution_refs", proposed)
        # Controller intent is still a claim without independent semantic evidence.
        self.assertEqual(decided["status"], "needs-confirmation")
        expanded = self.facade.handle(
            "trace", task_id="portable-task", object_ref=proposed["object_ref"]
        )
        self.assertEqual(expanded["object"]["action"]["type"], "pointer.click")

        pending = self.facade.handle(
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

    def test_run_exposes_the_bounded_automatic_transaction_loop(self):
        runtime = CoreOrchestrator(
            Compositor(),
            Executor(),
            proposal_provider=ProposalProvider(),
            policy_providers=(PolicyProvider(),),
        )
        facade = GuiRunFacade(runtime)
        response = facade.handle("run", task_contract=TASK, max_iterations=1, diagnostic=True)

        self.assertEqual(response["status"], "running")
        self.assertEqual(len(response["object"]["iterations"]), 1)
        self.assertEqual(response["retry"]["required_action"], "continue-run")

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
            {"single_action_only": True}, (),
        )
        return context, store

    def test_qwen_coordinate_is_mapped_to_desktop_logical_space(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(Backend(["pyautogui.click(500, 250)"]), store)
        proposal = provider.propose(context)
        self.assertEqual(proposal.action.coordinate, Point(900, 500))
        self.assertEqual(proposal.action.coordinate_space, "desktop-logical")

    def test_qwen_multiple_actions_are_rejected(self):
        context, store = self.context_and_store()
        provider = QwenCUAProposalProvider(
            Backend(["pyautogui.click(1, 1)", "pyautogui.click(2, 2)"]), store
        )
        with self.assertRaisesRegex(ValueError, "exactly one action"):
            provider.propose(context)

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
