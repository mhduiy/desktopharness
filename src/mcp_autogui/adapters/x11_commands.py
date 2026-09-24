"""Shared transport for X11 command-line tools.

Both the compositor adapter and the input adapter shell out to X11 utilities.
Query commands are decoded as UTF-8 explicitly: the target machines run a
zh_CN locale, so letting Python infer the codec from ``LC_ALL=C`` would make
Chinese window titles raise ``UnicodeDecodeError``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence


def run_command(
    argv: Sequence[str], *, c_locale: bool = False, timeout: float = 15.0
) -> subprocess.CompletedProcess:
    """Run one X11 query command and decode its output as UTF-8."""
    env = dict(os.environ)
    if c_locale:
        env["LC_ALL"] = "C"
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
    )


def run_binary(argv: Sequence[str], *, timeout: float = 15.0) -> bytes:
    """Run one X11 command whose stdout is binary (screenshots)."""
    completed = subprocess.run(
        list(argv), capture_output=True, timeout=timeout, check=False, env=dict(os.environ)
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(argv)}: "
            f"{detail[-1] if detail else 'no stderr'}"
        )
    return completed.stdout


Runner = Callable[..., subprocess.CompletedProcess]
BinaryRunner = Callable[..., bytes]
