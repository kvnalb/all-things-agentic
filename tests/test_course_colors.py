import unittest

from studyagent.taskmaster.course_colors import course_color_id, course_color_index


class CourseColorsTest(unittest.TestCase):
    def test_same_course_gets_stable_color(self) -> None:
        course = "DATA 144 (Fall 2026)"
        self.assertEqual(course_color_id(course), course_color_id(course))

    def test_hash_matches_frontend_algorithm(self) -> None:
        self.assertEqual(course_color_index("DATA 144"), 3)
        self.assertEqual(course_color_id("DATA 144"), "5")
