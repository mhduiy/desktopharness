"""Built-in provider registrations and their provider-owned configuration."""

from __future__ import annotations

from typing import Any

from ..provider_registry import (
    ProviderBuildContext,
    ProposalProviderRuntime,
    register_evidence_provider,
    register_policy_provider,
    register_proposal_provider,
)
from ..qwen_backend import QwenBackendClient
from .evidence import AtSpiEvidenceProvider, CompositorWindowEvidenceProvider, OmniParserEvidenceProvider
from .proposal import QwenCUAProposalProvider
from .policy import ActionRestrictionPolicyProvider


def register_builtin_providers() -> None:
    register_proposal_provider("qwen-cua", _validate_qwen, _build_qwen)
    register_evidence_provider("compositor_window", _validate_enabled, _build_compositor_window)
    register_evidence_provider("atspi", _validate_enabled, _build_atspi)
    register_evidence_provider("omniparser", _validate_omniparser, _build_omniparser)
    register_policy_provider(
        "action_restriction", _validate_action_restriction, _build_action_restriction
    )


def _validate_qwen(config: dict[str, Any], location: str) -> None:
    _only_keys(config, {
        "kind", "model", "base_url", "timeout_seconds", "tls_verify", "trust_env",
        "temperature", "top_p", "max_tokens",
        "max_response_chars", "max_history_turns", "coordinate_type", "resize_factor",
    }, location)
    _optional_string(config, "model", location)
    _optional_string(config, "base_url", location)
    _optional_positive_int(config, "timeout_seconds", location)
    _optional_bool(config, "tls_verify", location)
    _optional_bool(config, "trust_env", location)
    for name in ("max_tokens", "max_history_turns", "resize_factor"):
        _optional_positive_int(config, name, location)
    _optional_minimum_int(config, "max_response_chars", 1024, location)
    _optional_unit_interval(config, "temperature", location)
    _optional_unit_interval(config, "top_p", location)
    if "coordinate_type" in config and config["coordinate_type"] not in {"relative", "absolute"}:
        raise ValueError(f"{location}.coordinate_type must be 'relative' or 'absolute'")


def _build_qwen(config: dict[str, Any], store: Any) -> ProposalProviderRuntime:
    backend = QwenBackendClient(config)
    return ProposalProviderRuntime(
        provider=QwenCUAProposalProvider(backend, store),
        close=getattr(backend, "close", None),
    )


def _validate_enabled(config: dict[str, Any], location: str) -> None:
    _only_keys(config, {"enabled"}, location)
    _optional_bool(config, "enabled", location)


def _build_compositor_window(config: dict[str, Any], _context: ProviderBuildContext):
    return CompositorWindowEvidenceProvider() if config.get("enabled", True) else None


def _build_atspi(config: dict[str, Any], _context: ProviderBuildContext):
    if not config.get("enabled", False) or not AtSpiEvidenceProvider.available():
        return None
    return AtSpiEvidenceProvider()


def _validate_omniparser(config: dict[str, Any], location: str) -> None:
    _only_keys(config, {"enabled", "endpoint"}, location)
    _optional_bool(config, "enabled", location)
    _optional_string(config, "endpoint", location)
    if config.get("enabled", False) and not str(config.get("endpoint") or "").strip():
        raise ValueError(f"{location}.endpoint is required when enabled")


def _build_omniparser(config: dict[str, Any], context: ProviderBuildContext):
    if not config.get("enabled", False):
        return None

    def capture_frame() -> bytes:
        image, _, _ = context.capture_observation()
        return image

    return OmniParserEvidenceProvider(str(config["endpoint"]).strip(), capture_frame, context.store)


def _validate_action_restriction(config: dict[str, Any], location: str) -> None:
    from ..core.transaction import ActionType

    _only_keys(config, {"enabled", "denied_actions"}, location)
    _optional_bool(config, "enabled", location)
    denied_actions = config.get("denied_actions", [])
    if not isinstance(denied_actions, list) or any(
        not isinstance(item, str) for item in denied_actions
    ):
        raise ValueError(f"{location}.denied_actions must be an array of action strings")
    try:
        normalized = [ActionType(item) for item in denied_actions]
    except ValueError as exc:
        raise ValueError(f"{location}.denied_actions contains an unknown action") from exc
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{location}.denied_actions must not contain duplicates")
    if config.get("enabled", False) and not normalized:
        raise ValueError(f"{location}.denied_actions must not be empty when enabled")


def _build_action_restriction(config: dict[str, Any]):
    from ..core.transaction import ActionType

    if not config.get("enabled", False):
        return None
    return ActionRestrictionPolicyProvider(
        frozenset(ActionType(item) for item in config["denied_actions"])
    )


def _only_keys(config: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise ValueError(f"{location} has unknown fields: {', '.join(unknown)}")


def _required_string(config: dict[str, Any], name: str, location: str) -> str:
    value = config.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{name} must be a non-empty string")
    return value.strip()


def _optional_string(config: dict[str, Any], name: str, location: str) -> None:
    if name in config and not isinstance(config[name], str):
        raise ValueError(f"{location}.{name} must be a string")


def _optional_bool(config: dict[str, Any], name: str, location: str) -> None:
    if name in config and not isinstance(config[name], bool):
        raise ValueError(f"{location}.{name} must be true or false")


def _optional_positive_int(config: dict[str, Any], name: str, location: str) -> None:
    if name in config:
        value = config[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{location}.{name} must be a positive integer")


def _optional_minimum_int(config: dict[str, Any], name: str, minimum: int, location: str) -> None:
    if name in config:
        value = config[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{location}.{name} must be an integer of at least {minimum}")


def _optional_unit_interval(config: dict[str, Any], name: str, location: str) -> None:
    if name in config:
        value = config[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise ValueError(f"{location}.{name} must be a number from 0 to 1")
