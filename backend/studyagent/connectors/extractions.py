from __future__ import annotations

import asyncio

from google.cloud import firestore

from studyagent.models import AcademicEventCandidate, ExtractionRecord


class GoogleExtractionStore:
    def __init__(self, *, project: str) -> None:
        self._firestore = firestore.Client(project=project)

    async def save(
        self,
        record: ExtractionRecord,
        candidates: list[AcademicEventCandidate],
    ) -> None:
        await asyncio.to_thread(self._save_sync, record, candidates)

    def _save_sync(
        self,
        record: ExtractionRecord,
        candidates: list[AcademicEventCandidate],
    ) -> None:
        document = self._firestore.collection("extractions").document(record.id)
        batch = self._firestore.batch()
        for candidate in candidates:
            batch.set(
                document.collection("candidates").document(candidate.id),
                candidate.model_dump(mode="json"),
                merge=True,
            )
        batch.set(document, record.model_dump(mode="json"), merge=True)
        batch.commit(timeout=15)
