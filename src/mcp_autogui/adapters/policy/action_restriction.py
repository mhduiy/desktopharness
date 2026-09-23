"""Optional raw-action restriction for explicitly constrained deployments."""

from __future__ import annotations

from ...core.evidence import EvidenceConfidence
from ...core.task import TaskContract
from ...core.transaction import ActionProposal, ActionType, SemanticTag


class ActionRestrictionPolicyProvider:
    """Emit a deterministic deny tag when a Proposal uses configured actions."""

    provider_id = "action-restriction"

    def __init__(self, denied_actions: frozenset[ActionType]) -> None:
        if not denied_actions:
            raise ValueError("denied_actions must not be empty")
        self.denied_actions = denied_actions

    def independent_tags(
        self, proposal: ActionProposal, contract: TaskContract
    ) -> tuple[SemanticTag, ...]:
        del contract
        if not any(action.type in self.denied_actions for action in proposal.action_sequence):
            return ()
        return (
            SemanticTag(
                "action_restricted",
                self.provider_id,
                None,
                EvidenceConfidence.DETERMINISTIC,
            ),
        )
