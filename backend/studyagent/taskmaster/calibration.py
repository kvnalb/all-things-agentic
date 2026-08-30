"""Learned effort calibration from owner feedback."""

from __future__ import annotations

from datetime import UTC, datetime

from .cloud import State
from .models import CalibrationExample, CalibrationProfile, CourseCalibration, EffortFeedback

EMA_ALPHA = 0.2
MULTIPLIER_MIN = 0.5
MULTIPLIER_MAX = 2.5
HOURS_MIN = 0.25
HOURS_MAX = 20.0
MAX_EXAMPLES = 5
COURSE_SAMPLE_THRESHOLD = 2

RATING_RATIOS = {
    "too_low": 1.5,
    "about_right": 1.0,
    "too_high": 0.7,
}


def _clamp_multiplier(value: float) -> float:
    return max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, value))


def _ema(old: float, ratio: float) -> float:
    return _clamp_multiplier((1 - EMA_ALPHA) * old + EMA_ALPHA * ratio)


def feedback_ratio(feedback: EffortFeedback) -> float:
    if feedback.actual_hours is not None and feedback.estimated_hours > 0:
        return _clamp_multiplier(feedback.actual_hours / feedback.estimated_hours)
    return RATING_RATIOS[feedback.rating]


def load_profile() -> CalibrationProfile:
    value = State().db.collection("calibration").document("owner").get().to_dict() or {}
    return CalibrationProfile.model_validate(value)


def save_profile(profile: CalibrationProfile) -> None:
    State().db.collection("calibration").document("owner").set(
        {**profile.model_dump(mode="json"), "updated_at": datetime.now(UTC)}
    )


def effort_multiplier(course: str, profile: CalibrationProfile) -> float:
    course_entry = profile.by_course.get(course)
    if course_entry and course_entry.samples >= COURSE_SAMPLE_THRESHOLD:
        return course_entry.effort_multiplier
    if course_entry and course_entry.samples > 0:
        weight = course_entry.samples / COURSE_SAMPLE_THRESHOLD
        return _clamp_multiplier(
            weight * course_entry.effort_multiplier + (1 - weight) * profile.global_effort_multiplier
        )
    return profile.global_effort_multiplier


def apply_calibration(hours: float, course: str, profile: CalibrationProfile) -> float:
    adjusted = hours * effort_multiplier(course, profile)
    return round(max(HOURS_MIN, min(HOURS_MAX, adjusted)), 2)


def prompt_context(course: str, profile: CalibrationProfile) -> str:
    examples = [item for item in profile.recent_examples if item.course == course][:3]
    if not examples:
        return ""
    lines = [f"Recent effort calibration for {course}:"]
    for item in examples:
        detail = (
            f"actually {item.actual_hours}h"
            if item.actual_hours is not None
            else f"felt {item.rating.replace('_', ' ')}"
        )
        lines.append(
            f"- \"{item.title[:50]}\" was estimated {item.estimated_hours}h, {detail} "
            f"(ratio {item.ratio:.2f})."
        )
    multiplier = effort_multiplier(course, profile)
    if multiplier != 1.0:
        lines.append(f"Apply roughly a {multiplier:.2f}x adjustment for this course.")
    return "\n".join(lines)


def apply_feedback(profile: CalibrationProfile, feedback: EffortFeedback) -> CalibrationProfile:
    profile = profile.model_copy(deep=True)
    ratio = feedback_ratio(feedback)

    profile.global_effort_multiplier = _ema(profile.global_effort_multiplier, ratio)
    profile.global_samples += 1

    course_entry = profile.by_course.get(feedback.course, CourseCalibration())
    course_entry.effort_multiplier = _ema(course_entry.effort_multiplier, ratio)
    course_entry.samples += 1
    if feedback.course:
        profile.by_course[feedback.course] = course_entry

    profile.recent_examples.append(
        CalibrationExample(
            title=feedback.title,
            course=feedback.course,
            estimated_hours=feedback.estimated_hours,
            ratio=round(ratio, 3),
            rating=feedback.rating,
            actual_hours=feedback.actual_hours,
        )
    )
    profile.recent_examples = profile.recent_examples[-MAX_EXAMPLES:]
    return profile


def record_feedback(feedback: EffortFeedback) -> CalibrationProfile:
    profile = apply_feedback(load_profile(), feedback)
    save_profile(profile)
    return profile


def profile_summary(profile: CalibrationProfile) -> dict:
    return {
        "global_effort_multiplier": profile.global_effort_multiplier,
        "global_samples": profile.global_samples,
        "by_course": {
            course: entry.model_dump(mode="json")
            for course, entry in profile.by_course.items()
        },
        "recent_examples": [item.model_dump(mode="json") for item in profile.recent_examples],
    }
