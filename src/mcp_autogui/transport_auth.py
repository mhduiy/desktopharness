"""MCP transport authentication wiring."""

from __future__ import annotations

import hmac
import os

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from .server_config import ServerConfig


class StaticBearerTokenVerifier:
    """Validate a deployment-owned bearer token without exposing it in config output."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("bearer token must not be empty")
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id="autoui-mcp", scopes=[])


def fastmcp_auth_kwargs(config: ServerConfig) -> dict[str, object]:
    if config.transport_auth_mode != "bearer-token":
        return {}
    assert config.transport_token_env is not None
    token = os.environ[config.transport_token_env].strip()
    base_url = f"http://localhost:{config.transport_port}"
    return {
        "auth": AuthSettings(
            issuer_url=base_url,
            resource_server_url=f"{base_url}/mcp",
        ),
        "token_verifier": StaticBearerTokenVerifier(token),
    }
