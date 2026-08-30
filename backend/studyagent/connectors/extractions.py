from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from google.cloud import firestore

from studyagent.models import (
    AcademicEventCandidate,
    CandidateChange,
    CandidateStatus,
    ExtractionRecord,
)

_TRACKED_CANDIDATE_FIELDS = (
    "start_at",
    "end_at",
    "all_day_date",
    "title",
    "location",
    "status",
    "date_precision",
)


def _serialize_candidate_field(
    candidate: AcademicEventCandidate, field: str
) -> str | None:
    value = getattr(candidate, field)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, CandidateStatus):
        return value.value
    return str(value)


def diff_candidates(
    stored: AcademicEventCandidate,
    updated: AcademicEventCandidate,
    *,
    source_revision_id: str,
    detected_at: datetime,
) -> list[CandidateChange]:
    changes: list[CandidateChange] = []
    for field in _TRACKED_CANDIDATE_FIELDS:
        old_value = _serialize_candidate_field(stored, field)
        new_value = _serialize_candidate_field(updated, field)
        if old_value == new_value:
            continue
        changes.append(
            CandidateChange(
                id=uuid4().hex,
                candidate_id=stored.id,
                field=field,
                old_value=old_value,
                new_value=new_value,
                source_revision_id=source_revision_id,
                detected_at=detected_at,
            )
        )
    return changes


def reconcile_candidates(
    *,
    existing: list[AcademicEventCandidate],
    incoming: list[AcademicEventCandidate],
    source_revision_id: str,
    detected_at: datetime,
) -> tuple[list[AcademicEventCandidate], list[CandidateChange]]:
    existing_by_key = {candidate.identity_key: candidate for candidate in existing}
    incoming_keys = {candidate.identity_key for candidate in incoming}
    persisted: dict[str, AcademicEventCandidate] = {}
    changes: list[CandidateChange] = []

    for candidate in incoming:
        key = candidate.identity_key
        if key in existing_by_key:
            stored = existing_by_key[key]
            updated = candidate.model_copy(update={"id": stored.id})
            changes.extend(
                diff_candidates(
                    stored,
                    updated,
                    source_revision_id=source_revision_id,
                    detected_at=detected_at,
                )
            )
            persisted[stored.id] = updated
            continue
        persisted[candidate.id] = candidate

    for key, stored in existing_by_key.items():
        if key in incoming_keys:
            continue
        if stored.status is CandidateStatus.WITHDRAWN:
            persisted[stored.id] = stored
            continue
        withdrawn = stored.model_copy(
            update={
                "status": CandidateStatus.WITHDRAWN,
                "source_revision_id": source_revision_id,
            }
        )
        changes.extend(
            diff_candidates(
                stored,
                withdrawn,
                source_revision_id=source_revision_id,
                detected_at=detected_at,
            )
        )
        persisted[stored.id] = withdrawn

    return list(persisted.values()), changes


class GoogleExtractionStore:
    def __init__(self, *, project: str) -> None:
        self._firestore = firestore.Client(project=project)

    async def save(
        self,
        record: ExtractionRecord,
        candidates: list[AcademicEventCandidate],
    ) -> None:
        await asyncio.to_thread(self._save_sync, record, candidates)

    def _load_existing_candidates(self, source_id: str) -> list[AcademicEventCandidate]:
        collection = (
            self._firestore.collection("sources")
            .document(source_id)
            .collection("candidates")
        )
        return [
            AcademicEventCandidate.model_validate(snapshot.to_dict())
            for snapshot in collection.stream()
            if snapshot.to_dict()
        ]

    def _save_sync(
        self,
        record: ExtractionRecord,
        candidates: list[AcademicEventCandidate],
    ) -> None:
        document = self._firestore.collection("extractions").document(record.id)
        batch = self._firestore.batch()
        now = datetime.now(UTC)
        existing = self._load_existing_candidates(record.source_id)
        reconciled, changes = reconcile_candidates(
            existing=existing,
            incoming=candidates,
            source_revision_id=record.source_revision_id,
            detected_at=now,
        )
        reconciled_by_id = {candidate.id: candidate for candidate in reconciled}

        for candidate in candidates:
            canonical = reconciled_by_id.get(candidate.id, candidate)
            batch.set(
                document.collection("candidates").document(canonical.id),
                canonical.model_dump(mode="json"),
                merge=True,
            )

        source_candidates = (
            self._firestore.collection("sources")
            .document(record.source_id)
            .collection("candidates")
        )
        changes_collection = (
            self._firestore.collection("sources")
            .document(record.source_id)
            .collection("candidate_changes")
        )
        for candidate in reconciled:
            batch.set(
                source_candidates.document(candidate.id),
                candidate.model_dump(mode="json"),
                merge=True,
            )
        for change in changes:
            batch.set(
                changes_collection.document(change.id),
                change.model_dump(mode="json"),
                merge=True,
            )

        completed_record = record.model_copy(
            update={
                "candidate_ids": [
                    reconciled_by_id.get(candidate.id, candidate).id
                    for candidate in candidates
                ]
            }
        )
        batch.set(document, completed_record.model_dump(mode="json"), merge=True)
        batch.commit(timeout=15)
