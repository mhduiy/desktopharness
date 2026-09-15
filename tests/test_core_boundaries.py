from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
CORE = ROOT / "src" / "mcp_autogui" / "core"


class CoreBoundaryTests(unittest.TestCase):
    def test_core_implementation_modules_do_not_import_the_compatibility_aggregate(self):
        for path in CORE.glob("*.py"):
            if path.name in {"__init__.py", "models.py"}:
                continue
            self.assertNotIn("from .models import", path.read_text(encoding="utf-8"), path.name)

    def test_default_server_entrypoint_does_not_import_optional_langchain_clients(self):
        entrypoint = (ROOT / "src" / "mcp_autogui" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("langchain", entrypoint)
