"""Object-reference, ledger, and attribution bookkeeping for core transactions."""

from __future__ import annotations

from typing import Any

from .ledger import EventLedger
from .audit_models import (
    Attribution, AttributionEventKind, AttributionEvidenceStatus, AttributionOwner, AttributionStage,
)
from .protocol import ReasonCode, new_id
from .store import ObjectStore


class AuditRecorder:
    """Record causal audit facts without participating in policy or execution."""

    def __init__(self, store: ObjectStore | None = None, ledger: EventLedger | None = None) -> None:
        self.store = store or ObjectStore()
        self.ledger = ledger or EventLedger()
        self._object_events: dict[str, str] = {}
        self._primary_attribution: dict[str, str] = {}
        self._attribution_keys: set[tuple[str, str, ReasonCode]] = set()

    def append(self, task_id: str, event_type: str, object_ref: str, **kwargs: Any):
        event = self.ledger.append(task_id, event_type, object_ref, **kwargs)
        self._object_events[object_ref] = event.event_id
        return event

    def causes_for(self, object_ref: str) -> tuple[str, ...]:
        event_id = self._object_events.get(object_ref)
        return (event_id,) if event_id else ()

    def latest_execution_causes(self, task_id: str) -> tuple[str, ...]:
        selected: list[str] = []
        for event in reversed(self.ledger.events(task_id)):
            if event.event_type in {"execution.completed", "snapshot.created"}:
                if event.event_type not in {item.split(":", 1)[0] for item in selected}:
                    selected.append(f"{event.event_type}:{event.event_id}")
                if len(selected) == 2:
                    break
        return tuple(item.split(":", 1)[1] for item in reversed(selected))

    def record_attribution(
        self,
        task_id: str,
        event_kind: AttributionEventKind,
        stage: AttributionStage | str,
        owner: AttributionOwner | str,
        code: ReasonCode,
        summary: str,
        *,
        evidence_refs: tuple[str, ...] = (),
        evidence_status: AttributionEvidenceStatus = AttributionEvidenceStatus.CONFIRMED,
    ) -> Attribution:
        stage = AttributionStage(stage)
        owner = AttributionOwner(owner)
        key = (task_id, event_kind.value, code)
        if key in self._attribution_keys:
            return next(
                item
                for item in reversed(self.attributions(task_id))
                if item.event_kind == event_kind and item.code == code
            )
        is_primary = (
            task_id not in self._primary_attribution
            and event_kind in {AttributionEventKind.ERROR, AttributionEventKind.INCOMPLETE}
            and evidence_status != AttributionEvidenceStatus.INSUFFICIENT
        )
        attribution = Attribution(
            attribution_id=new_id("attribution"),
            event_kind=event_kind,
            stage=stage,
            owner=owner,
            code=code,
            evidence_status=evidence_status,
            primary=is_primary,
            summary=summary,
            evidence_refs=evidence_refs,
        )
        self.store.put(attribution, object_ref=attribution.attribution_id)
        self._attribution_keys.add(key)
        if is_primary:
            self._primary_attribution[task_id] = attribution.attribution_id
        self.append(
            task_id,
            "attribution.recorded",
            attribution.attribution_id,
            caused_by=tuple(
                self._object_events[reference]
                for reference in evidence_refs
                if reference in self._object_events
            ),
        )
        return attribution

    def attributions(self, task_id: str) -> tuple[Attribution, ...]:
        return tuple(
            self.store.require(event.object_ref)
            for event in self.ledger.events(task_id)
            if event.event_type == "attribution.recorded"
        )

    def primary_attribution(self, task_id: str) -> Attribution | None:
        reference = self._primary_attribution.get(task_id)
        return self.store.require(reference) if reference else None

    def primary_attribution_ref(self, task_id: str) -> str | None:
        return self._primary_attribution.get(task_id)

    def clear_task(self, task_id: str) -> None:
        self._primary_attribution.pop(task_id, None)
        self._attribution_keys = {
            item for item in self._attribution_keys if item[0] != task_id
        }
