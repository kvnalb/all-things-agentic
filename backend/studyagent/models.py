from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, Field, computed_field, model_validator


class ProviderName(StrEnum):
    GOOGLE = "google"
    CANVAS = "canvas"
    ED = "ed"
    COURSE_SOURCE = "course_source"


class ConnectionState(StrEnum):
    NOT_CONNECTED = "not_connected"
    VALIDATING = "validating"
    CONNECTED = "connected"
    ERROR = "error"


class ConnectionStatus(BaseModel):
    provider: ProviderName
    state: ConnectionState = ConnectionState.NOT_CONNECTED
    identity_label: str | None = None
    last_validated_at: datetime | None = None
    error: str | None = None


class ConnectorResult(BaseModel):
    provider: ProviderName
    state: ConnectionState
    identity_label: str | None = None
    discovered_course_ids: list[str] = Field(default_factory=list)
    message: str | None = None


class ExtractionMethod(StrEnum):
    API_FIELD = "api_field"
    ICS_FIELD = "ics_field"
    HTML_TABLE = "html_table"
    PROSE = "prose"
    PATTERN_INFERENCE = "pattern_inference"
    USER_ASSERTED = "user_asserted"


Confidence = Annotated[float, Field(ge=0, le=1)]


class Evidence(BaseModel):
    field: str = Field(min_length=1, max_length=64)
    source_id: str
    source_revision_id: str
    method: ExtractionMethod
    confidence: Confidence
    excerpt: str = Field(min_length=1, max_length=500)
    excerpt_start: int | None = Field(default=None, ge=0)
    excerpt_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> Evidence:
        if (self.excerpt_start is None) != (self.excerpt_end is None):
            raise ValueError("evidence offsets must be supplied together")
        if self.excerpt_start is not None and self.excerpt_end <= self.excerpt_start:
            raise ValueError("evidence end must follow evidence start")
        return self


class DatePrecision(StrEnum):
    EXACT = "exact"
    DATE_ONLY = "date_only"
    WEEK_ONLY = "week_only"
    UNKNOWN = "unknown"


class CandidateStatus(StrEnum):
    PUBLISHED = "published"
    PROJECTED = "projected"
    WITHDRAWN = "withdrawn"


class GradeComponent(BaseModel):
    id: str
    course_id: str
    name: str = Field(min_length=1, max_length=120)
    weight_pct: float = Field(ge=0, le=100)
    item_count: int | None = Field(default=None, ge=0)
    drop_lowest: int | None = Field(default=None, ge=0)
    evidence: list[Evidence] = Field(min_length=1)


def weights_complete(components: list[GradeComponent], tolerance: float = 0.01) -> bool:
    """True when a course's weights sum to 100. A shortfall means a component was missed."""
    return abs(sum(component.weight_pct for component in components) - 100.0) <= tolerance


class Course(BaseModel):
    id: str
    code: str
    title: str
    term: str
    canvas_id: str | None = None
    ed_id: str | None = None
    selected: bool = False
    grade_components: list[GradeComponent] = Field(default_factory=list)

    @computed_field
    @property
    def grade_weights_complete(self) -> bool:
        if not self.grade_components:
            return False
        return weights_complete(self.grade_components)


class SourceKind(StrEnum):
    CANVAS = "canvas"
    ED = "ed"
    URL = "url"
    UPLOAD = "upload"


class Source(BaseModel):
    id: str
    course_id: str
    kind: SourceKind
    label: str
    url: AnyHttpUrl | None = None
    current_revision_id: str | None = None
    current_revision_fetched_at: datetime | None = None


class SourceRevision(BaseModel):
    id: str
    source_id: str
    run_id: str
    content_hash: str
    media_type: str
    fetched_at: datetime
    parser_version: str
    object_ref: str | None = None
    normalized_ref: str | None = None


class IngestedSource(BaseModel):
    source: Source
    revision: SourceRevision


class EventKind(StrEnum):
    ASSIGNMENT = "assignment"
    QUIZ = "quiz"
    EXAM = "exam"
    PROJECT = "project"
    LECTURE = "lecture"
    DISCUSSION = "discussion"
    LAB = "lab"
    OFFICE_HOURS = "office_hours"
    OTHER = "other"


class AcademicEventCandidate(BaseModel):
    id: str
    course_id: str
    source_id: str
    source_revision_id: str
    kind: EventKind
    title: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day_date: date | None = None
    location: str | None = None
    recurrence: list[str] = Field(default_factory=list)
    source_url: AnyHttpUrl | None = None
    evidence: list[Evidence] = Field(min_length=1)
    external_source: str | None = Field(default=None, max_length=32)
    external_id: str | None = Field(default=None, max_length=128)
    date_precision: DatePrecision = DatePrecision.EXACT
    status: CandidateStatus = CandidateStatus.PUBLISHED
    hard_deadline: bool = False
    submitted: bool = False
    has_conflict: bool = False
    review_required: bool = False

    @property
    def identity_key(self) -> str:
        if self.external_id:
            return f"{self.external_source or 'unknown'}:{self.external_id}"
        return f"{self.course_id}:{self.kind.value}:{self.title.strip().lower()}"

    @property
    def confidence(self) -> float:
        """A fact is only as good as its weakest supporting field."""
        return min(item.confidence for item in self.evidence)

    @model_validator(mode="after")
    def validate_schedule(self) -> AcademicEventCandidate:
        if self.date_precision is DatePrecision.UNKNOWN:
            if self.start_at is not None or self.all_day_date is not None:
                raise ValueError("unknown precision cannot carry a date")
            return self
        if self.all_day_date is None and self.start_at is None:
            raise ValueError("candidate requires a date or start time")
        if self.all_day_date is not None and self.start_at is not None:
            raise ValueError("candidate cannot be both all-day and timed")
        if self.end_at is not None and self.start_at is None:
            raise ValueError("end time requires a start time")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end time must follow start time")
        return self

    @property
    def eligible_for_auto_import(self) -> bool:
        return (
            self.confidence >= 0.90
            and not self.submitted
            and not self.has_conflict
            and not self.review_required
            and bool(self.evidence)
            and self.date_precision is DatePrecision.EXACT
            and self.status is CandidateStatus.PUBLISHED
        )


class CandidateChange(BaseModel):
    id: str
    candidate_id: str
    field: str = Field(min_length=1, max_length=64)
    old_value: str | None = None
    new_value: str | None = None
    source_revision_id: str
    detected_at: datetime


class ExtractionState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionRecord(BaseModel):
    id: str
    run_id: str
    source_id: str
    source_revision_id: str
    state: ExtractionState
    extractor_version: str
    prompt_version: str
    model: str
    candidate_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ExtractionResult(BaseModel):
    record: ExtractionRecord
    candidates: list[AcademicEventCandidate] = Field(default_factory=list)


class CalendarBinding(BaseModel):
    studyagent_key: str
    candidate_id: str
    google_event_id: str
    source_revision: str
    synced_at: datetime


class ImportRunState(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    WRITING = "writing"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportRun(BaseModel):
    id: str
    state: ImportRunState = ImportRunState.PENDING
    created_at: datetime
    updated_at: datetime
    created_count: int = 0
    updated_count: int = 0
    submitted_skipped_count: int = 0
    review_count: int = 0
    errors: list[str] = Field(default_factory=list)
