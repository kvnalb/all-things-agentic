import unittest

from studyagent.taskmaster.calendar_link import public_calendar_url


class CalendarLinkTest(unittest.TestCase):
    def test_empty_id_opens_google_calendar(self) -> None:
        self.assertEqual(public_calendar_url(""), "https://calendar.google.com/calendar/r")
        self.assertEqual(public_calendar_url(None), "https://calendar.google.com/calendar/r")

    def test_encodes_group_calendar_id(self) -> None:
        url = public_calendar_url("abc123@group.calendar.google.com")
        self.assertTrue(url.startswith("https://calendar.google.com/calendar/r?cid="))
        self.assertIn("abc123", url)
        self.assertIn("%40", url)
