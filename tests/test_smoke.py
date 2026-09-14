import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mcp_autogui.smoke import _treeland_tree_check, main


def test_smoke_reports_effective_config_and_tree_check(capsys):
    payload = {
        "schema_version": 1,
        "transport": {"mode": "streamable-http", "host": "127.0.0.1", "port": 8651},
        "desktop_backend": {"kind": "treeland-deepin"},
        "proposal_provider": {"kind": "qwen-cua", "mode": "embedded", "base_url": "https://model.example/v1"},
    }
    with TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with patch("mcp_autogui.smoke._treeland_tree_check", return_value={"ok": True}):
            main(["--config", str(path)])
    assert json.loads(capsys.readouterr().out)["effective_config"]["transport"]["port"] == 8651


def test_smoke_marks_missing_treeland_debug_as_blocked():
    with patch("mcp_autogui.smoke.shutil.which", return_value=None):
        assert _treeland_tree_check() == {"ok": False, "reason": "treeland-debug is unavailable"}
