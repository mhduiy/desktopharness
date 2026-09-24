import asyncio
from types import SimpleNamespace
import unittest

from mcp_autogui.core.models import (
    Action,
    ActionProposal,
    ActionType,
    PolicyDecision,
    PolicyStatus,
    ReasonCode,
    TaskContract,
    TaskPermissions,
    TaskState,
)
from mcp_autogui.desktop_transactions import CoreDesktopTransactionRunner


class Runtime:
    def __init__(self):
        self.calls = []
        self.state = TaskState("desktop-task")

    def register_task(self, contract):
        self.calls.append("register")

    def observe(self, task_id):
        self.calls.append("observe")
        return SimpleNamespace(snapshot_id="desktop-snapshot")

    def submit_proposal(self, task_id, proposal):
        self.calls.append("submit")

    def decide(self, proposal_id):
        self.calls.append("decide")
        return PolicyDecision(proposal_id, PolicyStatus.DENY, ReasonCode.POLICY_DENIED)

    def execute(self, proposal_id):
        self.calls.append("execute")
        raise AssertionError("denied transactions must not execute")

    def status(self, task_id):
        self.calls.append("status")
        return self.state


async def run_blocking(function, /, *args, **kwargs):
    return function(*args, **kwargs)


class DesktopTransactionRunnerTests(unittest.TestCase):
    def test_runner_owns_the_core_transaction_sequence(self):
        runtime = Runtime()
        runner = CoreDesktopTransactionRunner(runtime, run_blocking)
        contract = TaskContract(
            "desktop-task",
            "invoke desktop capability",
            TaskPermissions(frozenset({ActionType.DONE})),
        )

        outcome = asyncio.run(
            runner.execute(
                contract,
                lambda observed: ActionProposal(
                    "proposal-1",
                    "desktop-tool",
                    observed.snapshot_id,
                    (Action(ActionType.DONE),),
                ),
            )
        )

        self.assertEqual(runtime.calls, ["register", "observe", "submit", "decide", "status"])
        self.assertEqual(outcome.decision.status, PolicyStatus.DENY)
        self.assertIsNone(outcome.receipt)


if __name__ == "__main__":
    unittest.main()
