"""Per-course colors shared between the dashboard and Google Calendar."""

from __future__ import annotations

# Index order matches frontend COURSE_PALETTE in scheduleColors.ts
COURSE_GCAL_COLOR_IDS = ("9", "4", "10", "5", "1", "7", "11", "3")


def course_color_index(name: str) -> int:
    value = 0
    for char in name:
        value = (value * 31 + ord(char)) & 0xFFFFFFFF
    return value % len(COURSE_GCAL_COLOR_IDS)


def course_color_id(course: str | None) -> str:
    return COURSE_GCAL_COLOR_IDS[course_color_index(course or "")]
