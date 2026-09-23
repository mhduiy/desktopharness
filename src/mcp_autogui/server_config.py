"""Server JSON configuration for the v2 MCP service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .desktop_backend import DEFAULT_DESKTOP_BACKEND, available_desktop_backends
from .provider_registry import (
    validate_evidence_provider,
    validate_policy_provider,
    validate_proposal_provider,
)


@dataclass(frozen=True)
class ServerConfig:
    path: Path
    transport_mode: str
    transport_host: str
    transport_port: int
    desktop_backend: str
    proposal_provider: dict[str, Any]
    policy_providers: dict[str, Any]
    evidence_providers: dict[str, Any]
    audit: dict[str, Any]

    def effective_config(self) -> dict[str, Any]:
        """Return the active non-secret configuration for logs and discovery."""
        provider = dict(self.proposal_provider)
        provider.pop("api_key", None)
        return {
            "config_path": str(self.path),
            "transport": {
                "mode": self.transport_mode,
                "host": self.transport_host,
                "port": self.transport_port,
            },
            "desktop_backend": self.desktop_backend,
            "proposal_provider": provider,
            "policy_providers": self.policy_providers,
            "evidence_providers": self.evidence_providers,
            "audit": self.audit,
        }


LEGACY_BEHAVIOUR_ENVIRONMENT = frozenset({
    "SSE_HOST",
    "SSE_PORT",
    "MCP_TRANSPORT",
    "CUA_BACKEND_MODE",
    "CUA_BACKEND_URL",
    "CUA_BACKEND_TIMEOUT",
    "CUA_TLS_VERIFY",
    "CUA_HTTP_TRUST_ENV",
    "CUA_AGENT_TYPE",
    "CUA_ROLLOUT_NUMS",
    "CUA_MODEL_BASE_URL",
    "CUA_MODEL",
    "CUA_MODEL_TIMEOUT",
    "CUA_MODEL_TLS_VERIFY",
    "CUA_MODEL_TRUST_ENV",
    "CUA_MAX_TOKENS",
    "CUA_MAX_RESPONSE_CHARS",
    "CUA_TOP_P",
    "CUA_TEMPERATURE",
    "CUA_MAX_HISTORY_TURNS",
    "CUA_COORDINATE_TYPE",
    "CUA_RESIZE_FACTOR",
    "GUI_OMNIPARSER_ENABLED",
    "OMNI_PARSER_SERVER",
    "GUI_AUDIT_DIR",
    "GUI_AUDIT_RETENTION_DAYS",
    "GUI_AUDIT_MAX_GIB",
})


def ignored_legacy_environment() -> tuple[str, ...]:
    """List legacy behaviour variables ignored when JSON config is selected.

    ``CUA_MODEL_API_KEY`` and backend API keys are deliberately excluded: they
    remain the supported secret-only environment inputs.
    """
    return tuple(sorted(name for name in LEGACY_BEHAVIOUR_ENVIRONMENT if os.getenv(name) is not None))


def load_server_config(path: str | Path) -> ServerConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"MCP config file does not exist: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP config file is not valid JSON: {config_path}: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError("MCP config root must be an object")
    _only_keys(
        raw,
        {
            "schema_version", "transport", "desktop_backend", "proposal_provider",
            "policy_providers", "evidence_providers", "audit",
        },
        "MCP config",
    )
    if raw.get("schema_version") != 1:
        raise ValueError("MCP config schema_version must be 1")

    transport = _object(raw, "transport")
    _only_keys(transport, {"mode", "host", "port"}, "transport")
    mode = _string(transport, "mode")
    if mode not in {"sse", "streamable-http"}:
        raise ValueError("transport.mode must be 'sse' or 'streamable-http'")
    host = _string(transport, "host")
    port = _positive_int(transport, "port")

    backend = _object(raw, "desktop_backend", default={"kind": DEFAULT_DESKTOP_BACKEND})
    _only_keys(backend, {"kind"}, "desktop_backend")
    backend_id = _string(backend, "kind")
    if backend_id not in available_desktop_backends():
        choices = ", ".join(available_desktop_backends())
        raise ValueError(f"desktop_backend.kind must be one of: {choices}")

    proposal_provider = _object(raw, "proposal_provider")
    validate_proposal_provider(proposal_provider, "proposal_provider")

    policy_providers = _object(raw, "policy_providers", default={})
    evidence_providers = _object(raw, "evidence_providers", default={})
    audit = _object(raw, "audit", default={})
    for provider_id, provider_config in policy_providers.items():
        if not isinstance(provider_config, dict):
            raise ValueError(f"policy_providers.{provider_id} must be an object")
        validate_policy_provider(provider_id, provider_config, f"policy_providers.{provider_id}")
    for provider_id, provider_config in evidence_providers.items():
        if not isinstance(provider_config, dict):
            raise ValueError(f"evidence_providers.{provider_id} must be an object")
        validate_evidence_provider(provider_id, provider_config, f"evidence_providers.{provider_id}")
    _only_keys(audit, {"directory", "retention_days", "max_gib"}, "audit")
    _optional_string(audit, "directory")
    _optional_positive_int(audit, "retention_days")
    _optional_positive_int(audit, "max_gib")
    return ServerConfig(
        path=config_path,
        transport_mode=mode,
        transport_host=host,
        transport_port=port,
        desktop_backend=backend_id,
        proposal_provider=proposal_provider,
        policy_providers=policy_providers,
        evidence_providers=evidence_providers,
        audit=audit,
    )


def _object(mapping: dict[str, Any], name: str, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    value = mapping.get(name, default)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _string(mapping: dict[str, Any], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _only_keys(mapping: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(f"{name} has unknown fields: {', '.join(unknown)}")


def _optional_string(mapping: dict[str, Any], name: str) -> None:
    if name in mapping and not isinstance(mapping[name], str):
        raise ValueError(f"{name} must be a string")


def _optional_bool(mapping: dict[str, Any], name: str) -> None:
    if name in mapping and not isinstance(mapping[name], bool):
        raise ValueError(f"{name} must be true or false")


def _optional_positive_int(mapping: dict[str, Any], name: str) -> None:
    if name not in mapping:
        return
    value = mapping[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _optional_minimum_int(mapping: dict[str, Any], name: str, minimum: int) -> None:
    if name not in mapping:
        return
    value = mapping[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")


def _optional_unit_interval(mapping: dict[str, Any], name: str) -> None:
    if name not in mapping:
        return
    value = mapping[name]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a number from 0 to 1")


def _positive_int(mapping: dict[str, Any], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
