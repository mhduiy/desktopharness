"""In-process Qwen-CUA backend wiring."""

from __future__ import annotations

from typing import Any, Mapping

from .qwen_cua_backend import QwenCUAService
from .qwen_cua_backend.service import QwenCUAConfig


class QwenBackendClient:
    """Expose the embedded Qwen-CUA service through the provider-facing API."""

    mode = "embedded"

    def __init__(self, provider_config: Mapping[str, object]) -> None:
        self._delegate = QwenCUAService(QwenCUAConfig.from_provider_config(provider_config))

    def init(self, session_id: str) -> dict[str, Any]:
        return self._delegate.init(session_id)

    def reset(self, session_id: str) -> None:
        self._delegate.reset(session_id)

    def predict(self, instruction: str, screenshot: bytes, session_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._delegate.predict(instruction, screenshot, session_id, **kwargs)

    def record_execution(
        self,
        session_id: str,
        *,
        status: str,
        execution: Any = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._delegate.record_execution(
            session_id, status=status, execution=execution, reason=reason
        )

    def health(self) -> dict[str, Any]:
        health = self._delegate.health()
        health.setdefault("backend_mode", self.mode)
        return health

    def close(self) -> None:
        self._delegate.close()
