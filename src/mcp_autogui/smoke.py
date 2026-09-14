"""Read-only preflight checks for a configured AutoUI MCP environment."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

from .server_config import load_server_config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run read-only AutoUI MCP preflight checks")
    parser.add_argument("--config", required=True, help="path to the server JSON configuration")
    args = parser.parse_args(argv)
    config = load_server_config(args.config)
    result = {
        "effective_config": config.effective_config(),
        "treeland_debug": _treeland_tree_check(),
        "proposal_provider": {
            "kind": config.proposal_provider["kind"],
            "mode": config.proposal_provider["mode"],
            "configured": bool(config.proposal_provider.get("base_url")),
        },
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["treeland_debug"]["ok"]:
        raise SystemExit(1)


def _treeland_tree_check() -> dict[str, object]:
    command = shutil.which("treeland-debug")
    if command is None:
        return {"ok": False, "reason": "treeland-debug is unavailable"}
    completed = subprocess.run(
        [command, "--json", "tree"], capture_output=True, text=True, timeout=10, check=False
    )
    try:
        tree = json.loads(completed.stdout) if completed.returncode == 0 else None
    except json.JSONDecodeError:
        tree = None
    return {"ok": isinstance(tree, dict), "returncode": completed.returncode}
