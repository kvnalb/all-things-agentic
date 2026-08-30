import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from studyagent.main import app
from studyagent.taskmaster.calibration import (
    apply_calibration,
    apply_feedback,
    effort_multiplier,
    feedback_ratio,
    prompt_context,
)
from studyagent.taskmaster.models import CalibrationProfile, CourseCalibration, EffortFeedback


class CalibrationLogicTest(unittest.TestCase):
    def test_actual_hours_override_rating(self) -> None:
        feedback = EffortFeedback(
            task_key="canvas:1",
            title="Problem Set",
            course="DATA 101",
            estimated_hours=4.0,
            rating="about_right",
            actual_hours=8.0,
        )
        self.assertAlmostEqual(feedback_ratio(feedback), 2.0)

    def test_ema_moves_multiplier_up_on_too_low(self) -> None:
        profile = CalibrationProfile()
        updated = apply_feedback(
            profile,
            EffortFeedback(
                task_key="canvas:1",
                title="Quiz",
                course="DATA 101",
                estimated_hours=2.0,
                rating="too_low",
            ),
        )
        self.assertGreater(updated.global_effort_multiplier, profile.global_effort_multiplier)
        self.assertEqual(updated.by_course["DATA 101"].samples, 1)

    def test_apply_calibration_clamps_hours(self) -> None:
        profile = CalibrationProfile(global_effort_multiplier=2.5)
        self.assertEqual(apply_calibration(10.0, "NEW 101", profile), 20.0)
        profile.global_effort_multiplier = 0.5
        self.assertEqual(apply_calibration(1.0, "NEW 101", profile), 0.5)

    def test_effort_multiplier_falls_back_to_global_for_new_course(self) -> None:
        profile = CalibrationProfile(global_effort_multiplier=1.3)
        self.assertEqual(effort_multiplier("UNKNOWN", profile), 1.3)

    def test_effort_multiplier_uses_course_after_enough_samples(self) -> None:
        profile = CalibrationProfile(
            global_effort_multiplier=1.0,
            by_course={"DATA 101": CourseCalibration(effort_multiplier=1.4, samples=2)},
        )
        self.assertEqual(effort_multiplier("DATA 101", profile), 1.4)

    def test_prompt_context_includes_recent_course_examples(self) -> None:
        profile = CalibrationProfile(
            global_effort_multiplier=1.2,
            recent_examples=[],
        )
        profile = apply_feedback(
            profile,
            EffortFeedback(
                task_key="canvas:2",
                title="Lab",
                course="MATH 110",
                estimated_hours=3.0,
                rating="too_low",
                actual_hours=5.0,
            ),
        )
        context = prompt_context("MATH 110", profile)
        self.assertIn("MATH 110", context)
        self.assertIn("Lab", context)


class CalibrationApiTest(unittest.TestCase):
    def test_feedback_requires_owner_session(self) -> None:
        client = TestClient(app)
        with patch("studyagent.taskmaster.api.State") as state:
            state.return_value.valid_session.return_value = False
            response = client.post(
                "/api/feedback",
                json={
                    "task_key": "canvas:1",
                    "title": "Essay",
                    "course": "HIST 100",
                    "estimated_hours": 4,
                    "rating": "too_low",
                },
            )
            self.assertEqual(response.status_code, 401)

    def test_feedback_persists_profile(self) -> None:
        client = TestClient(app)
        with (
            patch("studyagent.taskmaster.api.State") as state,
            patch("studyagent.taskmaster.calibration.State") as calibration_state,
        ):
            state.return_value.valid_session.return_value = True
            db = MagicMock()
            doc = MagicMock()
            doc.get.return_value.to_dict.return_value = {}
            db.collection.return_value.document.return_value = doc
            calibration_state.return_value.db = db
            response = client.post(
                "/api/feedback",
                json={
                    "task_key": "canvas:9",
                    "title": "Midterm prep",
                    "course": "DATA 101",
                    "estimated_hours": 5,
                    "rating": "too_low",
                    "actual_hours": 8,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "saved")
            doc.set.assert_called_once()


if __name__ == "__main__":
    unittest.main()
