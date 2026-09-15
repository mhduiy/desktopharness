import unittest

from mcp_autogui.core.desktop import CanonicalSnapshot
from mcp_autogui.core.evidence import AssertionResult
from mcp_autogui.core.models import CanonicalSnapshot as LegacyCanonicalSnapshot
from mcp_autogui.core.models import AssertionResult as LegacyAssertionResult
from mcp_autogui.core.models import TaskContract as LegacyTaskContract
from mcp_autogui.core.models import ActionProposal as LegacyActionProposal
from mcp_autogui.core.task import TaskContract
from mcp_autogui.core.transaction import ActionProposal


class DomainModelExportsTests(unittest.TestCase):
    def test_legacy_aggregate_reexports_the_domain_classes(self):
        self.assertIs(LegacyCanonicalSnapshot, CanonicalSnapshot)
        self.assertIs(LegacyTaskContract, TaskContract)
        self.assertIs(LegacyActionProposal, ActionProposal)
        self.assertIs(LegacyAssertionResult, AssertionResult)
