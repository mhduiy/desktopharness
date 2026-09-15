"""Compatibility exports for the v2 domain model modules.

New code imports the relevant domain module directly.  This module preserves
the established import surface while consumers migrate incrementally.
"""

from .audit_models import *  # noqa: F401,F403
from .context import *  # noqa: F401,F403
from .desktop import *  # noqa: F401,F403
from .evidence import *  # noqa: F401,F403
from .protocol import *  # noqa: F401,F403
from .task import *  # noqa: F401,F403
from .transaction import *  # noqa: F401,F403


CORE_OBJECT_TYPES = (
    AdapterDescriptor,
    CanonicalSnapshot,
    ActionProposal,
    PolicyDecision,
    ExecutionReceipt,
    AssertionResult,
)
