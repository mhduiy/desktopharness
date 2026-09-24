"""Desktop-backend assembly outside the compositor-neutral Core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .core.desktop import CanonicalSnapshot
from .core.store import ObjectStore
from .core.task import TaskContract, TaskState
from .core.proposal_validator import ValidationFailure
from .core.transaction import ActionProposal, ExecutionReceipt
from .ports.compositor import CompositorPort
from .ports.executor import ActionExecutor
from .ports.frame import FrameProvider


DEFAULT_DESKTOP_BACKEND = "treeland-deepin"


class DesktopTools(Protocol):
    """Backend-owned implementations behind the stable desktop MCP tools."""

    def list_capabilities(self, category: str = "") -> list[dict[str, Any]]: ...

    async def invoke_shortcut(self, capability_id: str) -> dict[str, Any]: ...

    def list_applications(self, query: str = "", limit: int = 30) -> list[dict[str, Any]]: ...

    async def launch_application(
        self,
        app_id: str,
        expected_active_app_id: str = "",
        application_wait_timeout_s: float = 3.0,
    ) -> dict[str, Any]: ...


RunBlocking = Callable[..., Awaitable[Any]]
ProposalBuilder = Callable[[CanonicalSnapshot], ActionProposal]


@dataclass(frozen=True, slots=True)
class DesktopTransactionResult:
    snapshot: CanonicalSnapshot
    proposal: ActionProposal
    validation: ValidationFailure | None
    receipt: ExecutionReceipt | None
    state: TaskState


class DesktopTransactionRunner(Protocol):
    async def execute(
        self,
        contract: TaskContract,
        proposal_builder: ProposalBuilder,
    ) -> DesktopTransactionResult: ...

    async def evaluate(self, task_id: str) -> TaskState: ...

    async def mark_delivered_unverified(self, task_id: str) -> TaskState: ...


DesktopToolsFactory = Callable[[DesktopTransactionRunner, RunBlocking], DesktopTools]


@dataclass(frozen=True)
class DesktopBackend:
    """Ports contributed by one desktop-session backend."""

    backend_id: str
    compositor: CompositorPort
    executor: ActionExecutor
    frame_provider: FrameProvider
    capture_observation: Callable[[], tuple[bytes, tuple[int, int], object]]
    create_tools: DesktopToolsFactory


DesktopBackendFactory = Callable[..., DesktopBackend]
_BACKEND_FACTORIES: dict[str, DesktopBackendFactory] = {}


def register_desktop_backend(backend_id: str, factory: DesktopBackendFactory) -> None:
    """Register one composition-root factory under a stable backend ID.

    Registration is deliberately outside Core: a new desktop adds an adapter
    bundle and calls this function during application composition.  Replacing
    an existing backend is rejected to keep configuration selection stable.
    """
    normalized = backend_id.strip()
    if not normalized:
        raise ValueError("desktop backend ID must be non-empty")
    if normalized in _BACKEND_FACTORIES:
        raise ValueError(f"desktop backend is already registered: {normalized}")
    _BACKEND_FACTORIES[normalized] = factory


def available_desktop_backends() -> tuple[str, ...]:
    return tuple(sorted(_BACKEND_FACTORIES))


def create_desktop_backend(
    backend_id: str,
    *,
    artifact_store: ObjectStore,
    **backend_options: Any,
) -> DesktopBackend:
    """Create one explicitly selected desktop backend from the registry."""
    factory = _BACKEND_FACTORIES.get(backend_id)
    if factory is None:
        choices = ", ".join(available_desktop_backends())
        raise ValueError(f"unsupported desktop backend {backend_id!r}; available: {choices}")
    return factory(artifact_store=artifact_store, **backend_options)


from .adapters.backends import register_builtin_backends

register_builtin_backends()
