---
name: deploy-desktop-harness
description: >-
  Deploy or repair DesktopHarness on a user-supplied desktop machine over SSH, start its MCP server
  in the real graphical session, and verify approved desktop-control probes across supported
  compositors.
---

# Deploy DesktopHarness

Use this skill only when the user wants a supplied physical desktop machine prepared or repaired as
a DesktopHarness MCP node. It does not create machines, run application tests, or alter the local
controller.

## Required connection data

Before any SSH command, obtain the hostname/IP, SSH username, and an authentication method. Do not
infer any of them. Prefer an SSH agent or identity file. For password authentication, use SSH's
interactive password prompt; never place a password in an argument, shell variable, file, log,
result, or JSON.

State the exact remote change plan and obtain confirmation immediately before running
`scripts/provision_remote.sh`. Checking connectivity and system state is read-only; installation,
updating, or starting a service is not.

## Workflow

1. Run `scripts/remote_exec.sh` for a bounded, read-only inventory. Collect the actual
   graphical-session user, session type, and environment from `loginctl` and
   `/proc/<session-leader>/environ`; do not invent `WAYLAND_DISPLAY`, `DISPLAY`,
   `XDG_RUNTIME_DIR`, or `DBUS_SESSION_BUS_ADDRESS`.
2. Check the current repository, `uv`, Python, dependencies, running process, configured backend,
   endpoint, and MCP describe request. Reuse healthy components. Run compositor-specific checks
   only when the selected backend requires them.
3. After approval, run `scripts/provision_remote.sh`. It clones only when the selected project
   directory is absent, updates only a clean existing checkout via fast-forward, and starts the
   server as the discovered desktop-session user.
4. Run `scripts/verify_mcp.py` against the endpoint. Observe and screenshot evidence are required.
   An input probe is deliberately opt-in: it must use a user-approved, harmless `task_contract` and
   `proposal` supplied in a JSON file; do not make up coordinates, keys, or a target application.
5. Return only the result schema in
   [references/acceptance-contract.md](references/acceptance-contract.md). `READY` requires every
   listed gate, not merely a PID or open port.

## Boundaries

- Retry SSH and HTTP requests at most twice after the initial attempt. Do not wait indefinitely.
- Never reset the system, upgrade the OS, overwrite a dirty checkout, modify project source, delete
  user data, or stop unrelated services.
- Do not expose a network endpoint wider than the user approved. The project configuration currently
  defaults to streamable HTTP at `/mcp`; report the endpoint actually configured.
- A generic deployment skill cannot make an unsupported compositor work. If the installed
  DesktopHarness backend does not support the detected compositor, stop at `DEPENDENCY` and report
  the backend mismatch.
- If desktop session discovery, required privilege, repository state, or a probe cannot be
  established, stop at the corresponding failure phase rather than guessing or compensating with
  broad system changes.

## Helpers

- `scripts/remote_exec.sh`: bounded SSH transport. Inputs come from `SSH_HOST`, `SSH_USER`,
  optional `SSH_PORT`, and optional `SSH_IDENTITY_FILE`.
- `scripts/provision_remote.sh`: idempotent remote inventory/install/start routine. It requires
  `SSH_HOST` and `SSH_USER`; review its generated remote plan before execution.
- `scripts/verify_mcp.py`: MCP protocol and evidence probe. Use `--input-probe` only with explicit
  authorization and a supplied JSON probe definition.
