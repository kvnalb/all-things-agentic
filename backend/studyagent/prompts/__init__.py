from importlib.resources import files


COURSE_EVENT_PROMPT_VERSION = "course-events-v1"


def course_event_instruction() -> str:
    return (
        files(__package__)
        .joinpath("course_event_extractor.md")
        .read_text(encoding="utf-8")
        .strip()
    )
