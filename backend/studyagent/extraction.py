from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from studyagent.agents.course_event_extractor import (
    AdkGeminiModel as _AdkGeminiModel,
)
from studyagent.models import (
    AcademicEventCandidate,
    EventKind,
    ExtractionRecord,
    ExtractionResult,
    ExtractionState,
    Source,
    SourceRevision,
)
from studyagent.prompts import COURSE_EVENT_PROMPT_VERSION


MAX_MODEL_SOURCE_CHARACTERS = 200_000
MAX_EXTRACTED_EVENTS = 200
EXTRACTOR_VERSION = "event-extractor-v1"
STUDY_TIME_ZONE = ZoneInfo("America/Los_Angeles")
RRULE_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
RRULE_KEYS = {"FREQ", "UNTIL", "COUNT", "INTERVAL", "BYDAY", "BYMONTHDAY"}
RRULE_DAY = re.compile(r"(?:[+-]?[1-5])?(?:MO|TU|WE|TH|FR|SA|SU)\Z")
TERM_PATTERN = re.compile(r"[A-Za-z0-9 '\u2019-]{1,80}\Z")

logger = logging.getLogger(__name__)


class ExtractionError(ValueError):
    """Model output failed closed and produced no importable candidates."""


def _valid_rrule(value: str) -> bool:
    if not value.startswith("RRULE:"):
        return False
    parts = value.removeprefix("RRULE:").split(";")
    pairs: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            return False
        key, item = part.split("=", 1)
        if key not in RRULE_KEYS or key in pairs or not item:
            return False
        pairs[key] = item
    if pairs.get("FREQ") not in RRULE_FREQUENCIES:
        return False
    for key in ("COUNT", "INTERVAL"):
        if key in pairs and (not pairs[key].isdigit() or int(pairs[key]) < 1):
            return False
    if "UNTIL" in pairs and not re.fullmatch(
        r"\d{8}(?:T\d{6}Z)?", pairs["UNTIL"]
    ):
        return False
    if "BYDAY" in pairs and not all(
        RRULE_DAY.fullmatch(day) for day in pairs["BYDAY"].split(",")
    ):
        return False
    if "BYMONTHDAY" in pairs:
        try:
            days = [int(day) for day in pairs["BYMONTHDAY"].split(",")]
        except ValueError:
            return False
        if not days or any(day == 0 or day < -31 or day > 31 for day in days):
            return False
    return True


def _has_los_angeles_offset(value: datetime) -> bool:
    if value.utcoffset() is None:
        return False
    round_trip = value.astimezone(UTC).astimezone(STUDY_TIME_ZONE)
    return (
        round_trip.replace(tzinfo=None) == value.replace(tzinfo=None)
        and round_trip.utcoffset() == value.utcoffset()
    )


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EventKind
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day_date: date | None = None
    location: str | None = Field(default=None, max_length=300)
    recurrence: list[str] = Field(default_factory=list, max_length=5)
    evidence: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_schedule(self) -> EventDraft:
        if (self.start_at is None) == (self.all_day_date is None):
            raise ValueError("event requires exactly one schedule shape")
        if self.end_at is not None and self.start_at is None:
            raise ValueError("end time requires a start time")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end time must follow start time")
        if self.start_at is not None and not _has_los_angeles_offset(self.start_at):
            raise ValueError("timed events require the Los Angeles UTC offset")
        if self.end_at is not None and not _has_los_angeles_offset(self.end_at):
            raise ValueError("end time requires the Los Angeles UTC offset")
        if any(not _valid_rrule(value) for value in self.recurrence):
            raise ValueError("recurrence must use supported RFC 5545 RRULE values")
        return self


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventDraft] = Field(
        default_factory=list, max_length=MAX_EXTRACTED_EVENTS
    )


class _VertexEventDraft(BaseModel):
    kind: EventKind
    title: str
    start_at: str | None = None
    end_at: str | None = None
    all_day_date: str | None = None
    location: str | None = None
    recurrence: list[str] = Field(default_factory=list)
    evidence: str
    confidence: float


class _VertexExtractionBatch(BaseModel):
    events: list[_VertexEventDraft] = Field(default_factory=list)


class StructuredModel(Protocol):
    model_name: str

    async def generate(self, prompt: str) -> str: ...


class ExtractionStore(Protocol):
    async def save(
        self,
        record: ExtractionRecord,
        candidates: list[AcademicEventCandidate],
    ) -> None: ...


class AdkGeminiModel(_AdkGeminiModel):
    def __init__(self, *, model: str | None = None) -> None:
        super().__init__(output_schema=_VertexExtractionBatch, model=model)


def build_extraction_prompt(*, normalized_text: str, term: str) -> str:
    if not TERM_PATTERN.fullmatch(term):
        raise ExtractionError("course term contains unsupported characters")
    return (
        f"Course term: {term}\n"
        "Timezone: America/Los_Angeles\n"
        "<course_source>\n"
        f"{normalized_text}\n"
        "</course_source>"
    )


class EventExtractor:
    def __init__(self, model: StructuredModel, store: ExtractionStore) -> None:
        self._model = model
        self._store = store

    async def extract(
        self,
        *,
        source: Source,
        revision: SourceRevision,
        normalized_text: str,
        term: str = "Fall 2026",
    ) -> ExtractionResult:
        if revision.source_id != source.id:
            raise ExtractionError("source revision does not belong to source")
        if not normalized_text.strip():
            raise ExtractionError("source contains no text")

        prompt = build_extraction_prompt(
            normalized_text=normalized_text,
            term=term,
        )
        if len(prompt) > MAX_MODEL_SOURCE_CHARACTERS:
            raise ExtractionError("model input exceeds the character limit")

        now = datetime.now(UTC)
        run_id = uuid4().hex
        record = ExtractionRecord(
            id=run_id,
            run_id=run_id,
            source_id=source.id,
            source_revision_id=revision.id,
            state=ExtractionState.RUNNING,
            extractor_version=EXTRACTOR_VERSION,
            prompt_version=COURSE_EVENT_PROMPT_VERSION,
            model=self._model.model_name,
            created_at=now,
            updated_at=now,
        )
        await self._store.save(record, [])

        try:
            raw_output = await self._model.generate(prompt)
            raw_batch = json.loads(raw_output)
            _VertexExtractionBatch.model_validate(raw_batch)
            for event in raw_batch.get("events", []):
                recurrence = event.get("recurrence") or []
                if any(not _valid_rrule(value) for value in recurrence):
                    event["recurrence"] = []
            batch = ExtractionBatch.model_validate(raw_batch)
            candidates = self._candidates(
                source=source,
                revision=revision,
                normalized_text=normalized_text,
                batch=batch,
            )
        except Exception as exc:
            failed = record.model_copy(
                update={
                    "state": ExtractionState.FAILED,
                    "error_code": type(exc).__name__,
                    "updated_at": datetime.now(UTC),
                }
            )
            try:
                await self._store.save(failed, [])
            except Exception:
                logger.exception(
                    "failed extraction state could not be persisted",
                    extra={"run_id": run_id, "source_id": source.id},
                )
            if isinstance(exc, ExtractionError):
                raise
            raise ExtractionError("event extraction output failed closed") from exc

        completed = record.model_copy(
            update={
                "state": ExtractionState.COMPLETED,
                "candidate_ids": [candidate.id for candidate in candidates],
                "updated_at": datetime.now(UTC),
            }
        )
        await self._store.save(completed, candidates)
        return ExtractionResult(record=completed, candidates=candidates)

    @staticmethod
    def _candidates(
        *,
        source: Source,
        revision: SourceRevision,
        normalized_text: str,
        batch: ExtractionBatch,
    ) -> list[AcademicEventCandidate]:
        candidates: list[AcademicEventCandidate] = []
        for draft in batch.events:
            evidence_start = normalized_text.find(draft.evidence)
            if evidence_start < 0:
                continue
            evidence_end = evidence_start + len(draft.evidence)
            digest = hashlib.sha256(
                f"{revision.id}:{draft.model_dump_json()}".encode()
            ).hexdigest()[:24]
            candidates.append(
                AcademicEventCandidate(
                    id=digest,
                    course_id=source.course_id,
                    source_id=source.id,
                    source_revision_id=revision.id,
                    source_url=source.url,
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                    review_required=True,
                    **draft.model_dump(),
                )
            )
        return candidates
