"""Immutable description of components selected by the composition root."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from .core.protocol import to_primitive
from .ports.compositor import CompositorPort
from .ports.evidence import EvidenceProvider
from .ports.executor import ActionExecutor
from .ports.frame import FrameProvider
from .ports.policy import PolicyProvider
from .ports.proposal import ProposalProvider


@dataclass(frozen=True, slots=True)
class RuntimeDescription:
    """Read-only snapshot used only by the protocol describe operation."""

    _serialized: str

    @classmethod
    def from_components(
        cls,
        *,
        compositor: CompositorPort,
        executor: ActionExecutor | None,
        proposal_provider: ProposalProvider | None,
        frame_provider: FrameProvider | None,
        policy_providers: Sequence[PolicyProvider],
        evidence_providers: Sequence[EvidenceProvider],
        policy_profiles: Iterable[str],
        context_strategies: Iterable[str],
        effective_config: Mapping[str, Any] | None = None,
    ) -> RuntimeDescription:
        descriptor = compositor.descriptor
        description = {
            "protocol_version": 2,
            "schema_version": "1",
            "schema_revision": "2.1-p4",
            "adapter": to_primitive(descriptor),
            "capabilities": {
                "pointer": executor is not None,
                "keyboard": executor is not None,
                "window_geometry": descriptor.capabilities.desktop_geometry,
                "frame": frame_provider is not None,
                "child_control_semantics": descriptor.capabilities.child_controls,
            },
            "providers": {
                "proposal": _component_id(proposal_provider, "provider_id"),
                "frame": _component_id(frame_provider, "provider_id"),
                "policy": [
                    _component_id(provider, "provider_id") for provider in policy_providers
                ],
                "evidence": [
                    {
                        "provider_id": provider.provider_id,
                        "fact_paths": sorted(provider.fact_paths),
                    }
                    for provider in evidence_providers
                ],
                "executor": _component_id(executor, "executor_id"),
            },
            "context_strategies": sorted(context_strategies),
            "policy_profiles": sorted(policy_profiles),
        }
        if effective_config is not None:
            description["effective_config"] = to_primitive(effective_config)
        return cls(json.dumps(description, ensure_ascii=False, sort_keys=True))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._serialized)


def _component_id(component: object | None, attribute: str) -> str | None:
    if component is None:
        return None
    return str(getattr(component, attribute, type(component).__name__))
