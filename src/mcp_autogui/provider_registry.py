"""Composition-root registry for proposal and evidence adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .core.store import ObjectStore
from .ports.evidence import EvidenceProvider
from .ports.proposal import ProposalProvider


@dataclass(frozen=True)
class ProposalProviderRuntime:
    provider: ProposalProvider
    close: Callable[[], None] | None = None


@dataclass(frozen=True)
class ProviderBuildContext:
    store: ObjectStore
    capture_observation: Callable[[], tuple[bytes, tuple[int, int], object]]


ProposalValidator = Callable[[dict[str, Any], str], None]
ProposalFactory = Callable[[dict[str, Any], ObjectStore], ProposalProviderRuntime]
EvidenceValidator = Callable[[dict[str, Any], str], None]
EvidenceFactory = Callable[[dict[str, Any], ProviderBuildContext], EvidenceProvider | None]

_PROPOSAL_PROVIDERS: dict[str, tuple[ProposalValidator, ProposalFactory]] = {}
_EVIDENCE_PROVIDERS: dict[str, tuple[EvidenceValidator, EvidenceFactory]] = {}


def register_proposal_provider(kind: str, validator: ProposalValidator, factory: ProposalFactory) -> None:
    _register(_PROPOSAL_PROVIDERS, kind, validator, factory, "proposal provider")


def register_evidence_provider(kind: str, validator: EvidenceValidator, factory: EvidenceFactory) -> None:
    _register(_EVIDENCE_PROVIDERS, kind, validator, factory, "evidence provider")


def available_proposal_providers() -> tuple[str, ...]:
    return tuple(sorted(_PROPOSAL_PROVIDERS))


def available_evidence_providers() -> tuple[str, ...]:
    return tuple(sorted(_EVIDENCE_PROVIDERS))


def validate_proposal_provider(config: dict[str, Any], location: str) -> None:
    kind = _kind(config, location)
    validator, _ = _proposal_entry(kind, location)
    validator(config, location)


def validate_evidence_provider(kind: str, config: dict[str, Any], location: str) -> None:
    validator, _ = _evidence_entry(kind, location)
    validator(config, location)


def create_proposal_provider(config: dict[str, Any], store: ObjectStore) -> ProposalProviderRuntime:
    kind = _kind(config, "proposal_provider")
    validator, factory = _proposal_entry(kind, "proposal_provider")
    validator(config, "proposal_provider")
    return factory(config, store)


def create_evidence_providers(
    configs: dict[str, Any], context: ProviderBuildContext
) -> tuple[EvidenceProvider, ...]:
    providers: list[EvidenceProvider] = []
    for kind, raw_config in configs.items():
        if not isinstance(raw_config, dict):
            raise ValueError(f"evidence_providers.{kind} must be an object")
        location = f"evidence_providers.{kind}"
        validator, factory = _evidence_entry(kind, location)
        validator(raw_config, location)
        provider = factory(raw_config, context)
        if provider is not None:
            providers.append(provider)
    return tuple(providers)


def _register(registry: dict, kind: str, validator: Callable, factory: Callable, label: str) -> None:
    normalized = kind.strip()
    if not normalized:
        raise ValueError(f"{label} ID must be non-empty")
    if normalized in registry:
        raise ValueError(f"{label} is already registered: {normalized}")
    registry[normalized] = (validator, factory)


def _kind(config: dict[str, Any], location: str) -> str:
    kind = config.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError(f"{location}.kind must be a non-empty string")
    return kind.strip()


def _proposal_entry(kind: str, location: str) -> tuple[ProposalValidator, ProposalFactory]:
    entry = _PROPOSAL_PROVIDERS.get(kind)
    if entry is None:
        choices = ", ".join(available_proposal_providers())
        raise ValueError(f"{location}.kind must be one of: {choices}")
    return entry


def _evidence_entry(kind: str, location: str) -> tuple[EvidenceValidator, EvidenceFactory]:
    entry = _EVIDENCE_PROVIDERS.get(kind)
    if entry is None:
        choices = ", ".join(available_evidence_providers())
        raise ValueError(f"{location} must be one of: {choices}")
    return entry


from .adapters.providers import register_builtin_providers

register_builtin_providers()
