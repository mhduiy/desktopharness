#!/usr/bin/env python3
"""Bounded DesktopHarness MCP verification; input injection is opt-in and caller supplied."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def call(endpoint: str, method: str, params: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": f"probe-{time.time_ns()}",
        "method": method,
        "params": params,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:  # explicit user-supplied endpoint
        value = json.loads(response.read().decode())
    if not isinstance(value, dict) or "error" in value:
        raise RuntimeError(str(value.get("error", value)))
    return value


def tool(endpoint: str, name: str, arguments: dict) -> dict:
    return call(endpoint, "tools/call", {"name": name, "arguments": arguments})


def structured(value: dict) -> dict:
    """Accept both FastMCP structuredContent and JSON text content responses."""
    result = value.get("result", {})
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for item in result.get("content", []):
        if item.get("type") == "text":
            decoded = json.loads(item.get("text", ""))
            if isinstance(decoded, dict):
                return decoded
    raise RuntimeError("MCP tool result has no structured object")


def run_input_probe(endpoint: str, probe: dict) -> tuple[bool, str]:
    for required in ("task_contract", "proposal"):
        if required not in probe:
            raise ValueError(f"input probe lacks {required}")
    proposed = structured(tool(endpoint, "gui_diagnostic", {"operation": "propose", **probe}))
    proposal_id = proposed.get("object_ref", "")
    if not proposal_id:
        raise RuntimeError("input proposal did not return an object_ref")
    executed = structured(tool(endpoint, "gui_diagnostic", {
        "operation": "execute", "task_id": probe["task_contract"]["task_id"],
        "proposal_id": proposal_id, "confirmed": True,
    }))
    if executed.get("status") != "running":
        raise RuntimeError("input action was not delivered")
    return True, str(probe["proposal"].get("action", {}).get("type", ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument(
        "--input-probe",
        type=Path,
        help="Approved JSON with task_contract and proposal",
    )
    args = parser.parse_args()
    result = {"endpoint": args.endpoint, "mcp_reachable": False, "observe": False,
              "screenshot": False, "pointer": False, "keyboard": False}
    try:
        tool(args.endpoint, "gui_run", {"operation": "describe"})
        result["mcp_reachable"] = True
        contract = {"task_id": "provision-observe", "goal": "Read the current desktop only.",
                    "permissions": {"actions": []}, "limits": {"max_steps": 1, "max_retries": 0}}
        observed = structured(
            tool(
                args.endpoint,
                "gui_diagnostic",
                {"operation": "observe", "task_contract": contract},
            )
        )
        result["observe"] = observed.get("status") == "ok" and bool(observed.get("object"))
        # A successful observe response is the server's supported screenshot/frame evidence probe.
        result["screenshot"] = result["observe"]
        if args.input_probe:
            probes = json.loads(args.input_probe.read_text(encoding="utf-8")).get("probes", [])
            if not isinstance(probes, list) or len(probes) != 2:
                raise ValueError("input probe must contain exactly two approved probes")
            for probe in probes:
                ok, action = run_input_probe(args.endpoint, probe)
                result["pointer"] |= ok and action.startswith("pointer.")
                result["keyboard"] |= ok and action.startswith("keyboard.")
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        result["error"] = type(exc).__name__
        print(json.dumps(result, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["mcp_reachable"] and result["observe"] and result["screenshot"] else 1


if __name__ == "__main__":
    sys.exit(main())
