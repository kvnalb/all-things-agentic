import sqlite3
import tempfile
import unittest
from pathlib import Path

from studyagent.demo_loader import build_demo_registry, demo_mode_enabled, resolve_demo_db_path
from studyagent.taskmaster.models import ClaimStatus, EventKind


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE courses (
  slug TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  term TEXT NOT NULL,
  units INTEGER,
  canvas_id INTEGER,
  ed_id INTEGER,
  website TEXT,
  ics_url TEXT,
  platform_note TEXT
);
CREATE TABLE assignments (
  id INTEGER PRIMARY KEY,
  course_slug TEXT NOT NULL REFERENCES courses(slug),
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  seq INTEGER,
  posted_at TEXT,
  due_at TEXT,
  due_precision TEXT,
  hard_deadline INTEGER,
  lock_at TEXT,
  points REAL,
  group_name TEXT,
  submit_via TEXT,
  url TEXT,
  est_hours REAL,
  status TEXT NOT NULL,
  needs_review INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  course_slug TEXT REFERENCES courses(slug),
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT,
  duration_min INTEGER,
  location TEXT,
  rrule TEXT,
  exdates TEXT,
  section TEXT,
  is_mine INTEGER,
  optional INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  needs_review INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE event_occurrences (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  start_at TEXT NOT NULL,
  end_at TEXT
);
CREATE TABLE grade_components (
  id INTEGER PRIMARY KEY,
  course_slug TEXT NOT NULL REFERENCES courses(slug),
  name TEXT NOT NULL,
  weight_pct REAL,
  count INTEGER,
  drop_lowest INTEGER,
  note TEXT
);
CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  course_slug TEXT,
  kind TEXT NOT NULL,
  url TEXT NOT NULL,
  path TEXT,
  http_status INTEGER,
  fetched_at TEXT NOT NULL,
  sha256 TEXT
);
CREATE TABLE provenance (
  id INTEGER PRIMARY KEY,
  table_name TEXT NOT NULL,
  row_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  source_id INTEGER NOT NULL,
  method TEXT NOT NULL,
  confidence TEXT NOT NULL,
  excerpt TEXT,
  note TEXT
);
"""


class DemoLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "demo.db"
        connection = sqlite3.connect(self.db_path)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "data-144",
                "DATA 144",
                "Data Mining",
                "Fall 2026",
                3,
                1557529,
                None,
                None,
                None,
                "Canvas only",
            ),
        )
        connection.execute(
            "INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                "data-144",
                "Lab 1",
                "lab",
                1,
                None,
                "2026-09-09T12:00:00-07:00",
                "datetime",
                0,
                None,
                10.0,
                None,
                "canvas",
                "https://example.edu/lab1",
                None,
                "published",
                0,
            ),
        )
        connection.execute(
            "INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                2,
                "data-144",
                "Problem Set 1",
                "problem_set",
                1,
                None,
                "2026-09-09T17:00:00-07:00",
                "unknown",
                1,
                None,
                None,
                None,
                "gradescope",
                None,
                None,
                "placeholder",
                1,
            ),
        )
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                "data-144",
                "Lecture",
                "lecture",
                "2026-09-02T14:00:00-07:00",
                "2026-09-02T17:00:00-07:00",
                180,
                "Zoom",
                None,
                None,
                None,
                1,
                0,
                "confirmed",
                0,
            ),
        )
        connection.execute(
            "INSERT INTO event_occurrences VALUES (?,?,?,?)",
            (1, 1, "2026-09-02T14:00:00-07:00", "2026-09-02T17:00:00-07:00"),
        )
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                2,
                "data-144",
                "Midterm Exam",
                "exam",
                "2026-10-21T14:00:00-07:00",
                "2026-10-21T16:00:00-07:00",
                120,
                "Wheeler 150",
                None,
                None,
                None,
                1,
                0,
                "confirmed",
                0,
            ),
        )
        connection.execute(
            "INSERT INTO grade_components VALUES (?,?,?,?,?,?,?)",
            (1, "data-144", "Labs", 30.0, None, None, None),
        )
        connection.execute(
            "INSERT INTO grade_components VALUES (?,?,?,?,?,?,?)",
            (2, "data-144", "Final Project", 70.0, None, None, None),
        )
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (1, "data-144", "canvas_api", "https://example.edu/api", "raw/api.json", 200, "2026-08-30T00:00:00+00:00", "abc"),
        )
        connection.execute(
            "INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?)",
            (
                1,
                "assignments",
                1,
                "due_at",
                1,
                "api_field",
                "exact",
                "2026-09-09T12:00:00-07:00",
                None,
            ),
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_build_demo_registry_maps_assignments_events_and_coverage(self) -> None:
        registry = build_demo_registry(
            {"selected_course_ids": ["1557529"]},
            run_id="run-demo",
            db_path=self.db_path,
        )
        self.assertEqual(len(registry["canonical"]), 2)
        ready = [item for item in registry["canonical"] if item.status == ClaimStatus.READY]
        review = [item for item in registry["canonical"] if item.status == ClaimStatus.REVIEW_REQUIRED]
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(review), 1)
        self.assertEqual(len(registry["timed_events"]), 1)
        self.assertEqual(registry["timed_events"][0].kind, EventKind.EXAM)
        self.assertEqual(registry["timed_events"][0].title, "Midterm Exam")
        course = registry["coverage"]["courses"][0]
        self.assertTrue(course["grade_weights_complete"])
        self.assertEqual(course["needs_review_assignments"], 1)
        self.assertEqual(course["timed_events"], 1)

    def test_resolve_demo_db_path_points_at_repo_demo_database(self) -> None:
        path = resolve_demo_db_path()
        self.assertTrue(path.name == "deadlines.db")
        self.assertEqual(path.parent.name, "data")


class DemoModeFlagTest(unittest.TestCase):
    def test_demo_mode_enabled_reads_environment(self) -> None:
        import os

        original = os.environ.get("STUDYAGENT_DATA_SOURCE")
        try:
            os.environ["STUDYAGENT_DATA_SOURCE"] = "demo"
            self.assertTrue(demo_mode_enabled())
            os.environ["STUDYAGENT_DATA_SOURCE"] = "live"
            self.assertFalse(demo_mode_enabled())
        finally:
            if original is None:
                os.environ.pop("STUDYAGENT_DATA_SOURCE", None)
            else:
                os.environ["STUDYAGENT_DATA_SOURCE"] = original


class DemoFixtureIntegrationTest(unittest.TestCase):
    def test_real_demo_database_loads_five_courses(self) -> None:
        db_path = resolve_demo_db_path()
        if not db_path.is_file():
            self.skipTest("demo database is not present locally")
        registry = build_demo_registry({"selected_course_ids": []}, run_id="run-all", db_path=db_path)
        self.assertEqual(len(registry["coverage"]["courses"]), 5)
        self.assertGreater(len(registry["canonical"]), 70)
        self.assertEqual(len(registry["timed_events"]), 18)
        self.assertEqual(registry["coverage"]["data_source"], "demo")


if __name__ == "__main__":
    unittest.main()
