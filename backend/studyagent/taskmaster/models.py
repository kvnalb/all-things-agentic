from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Task(BaseModel):
    source: str
    source_ref: str
    candidate_id: str | None = None
    source_revision_id: str | None = None
    title: str
    course: str = ""
    description: str = ""
    due_at: datetime
    source_url: str | None = None
    points_possible: float | None = None
    course_total_points: float | None = None
    submitted: bool = False
    date_only: bool = False
    estimated_hours: float | None = Field(default=None, ge=0.25, le=20)
    raw_estimated_hours: float | None = Field(default=None, ge=0.25, le=20)
    estimate_confidence: str | None = None
    priority_score: float | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_ref}"


class UserConfig(BaseModel):
    selected_course_ids: list[str] = Field(default_factory=list)
    priority_mode: str = "grade"
    lead_time_days: int = Field(default=5, ge=0, le=21)
    reminder_style: str = "ramping"
    work_day_start: int = Field(default=9, ge=0, le=23)
    work_day_end: int = Field(default=21, ge=1, le=24)
    off_days: list[str] = Field(default_factory=list)
    priority_courses: list[str] = Field(default_factory=list)
    excluded_courses: list[str] = Field(default_factory=list)
    daily_cap_hours: float = Field(default=4, ge=0.5, le=24)
    effort_padding: float = Field(default=1.2, ge=1, le=2)


class StudyBlock(BaseModel):
    key: str
    task_key: str
    title: str
    course: str
    start_at: datetime
    end_at: datetime
    color_id: str
    priority_score: float
    source_url: str | None = None


EffortRating = Literal["too_low", "about_right", "too_high"]


class EffortFeedback(BaseModel):
    task_key: str
    title: str
    course: str = ""
    estimated_hours: float = Field(ge=0.25, le=20)
    rating: EffortRating
    actual_hours: float | None = Field(default=None, ge=0.25, le=40)


class CourseCalibration(BaseModel):
    effort_multiplier: float = 1.0
    samples: int = 0


class CalibrationExample(BaseModel):
    title: str
    course: str
    estimated_hours: float
    ratio: float
    rating: EffortRating | None = None
    actual_hours: float | None = None


class CalibrationProfile(BaseModel):
    global_effort_multiplier: float = 1.0
    global_samples: int = 0
    by_course: dict[str, CourseCalibration] = Field(default_factory=dict)
    recent_examples: list[CalibrationExample] = Field(default_factory=list)


class TaskBriefing(BaseModel):
    task_key: str
    title: str
    course: str
    due_at: datetime
    rank: float
    budgeted_hours: float
    blocks: int
    fully_scheduled: bool
    priority_course: bool
    from_syllabus: bool
    recommended_start: datetime
