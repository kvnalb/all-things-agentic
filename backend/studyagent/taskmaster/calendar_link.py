from urllib.parse import quote


def public_calendar_url(calendar_id: str | None) -> str:
    if not calendar_id:
        return "https://calendar.google.com/calendar/r"
    return f"https://calendar.google.com/calendar/r?cid={quote(str(calendar_id), safe='')}"
