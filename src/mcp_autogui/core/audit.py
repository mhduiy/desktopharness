"""Optional lightweight persistence wiring for audit-only v2 data."""

from __future__ import annotations

from typing import Mapping

from .ledger import CsvAuditEventLedger, EventLedger
from .store import JsonAuditObjectStore, ObjectStore


AuditTrail = tuple[ObjectStore, EventLedger]


def audit_components_from_config(config: Mapping[str, object] | None) -> tuple[ObjectStore, EventLedger]:
    """Create audit persistence from v2 config without process-wide state."""
    if config is None:
        return ObjectStore(), EventLedger()
    directory = str(config.get("directory") or "").strip()
    return _audit_components(
        directory,
        retention_days=int(config.get("retention_days") or 7),
        max_gib=int(config.get("max_gib") or 16),
    )


def _audit_components(
    directory: str,
    *,
    retention_days: int,
    max_gib: int,
) -> tuple[ObjectStore, EventLedger]:
    if not directory:
        return ObjectStore(), EventLedger()
    return (
        JsonAuditObjectStore(
            directory,
            retention_days=retention_days,
            max_total_bytes=max_gib * 1024 * 1024 * 1024,
        ),
        CsvAuditEventLedger(directory),
    )
