import unittest

from scripts.check_pr_gate import (
    disclosed_decisions,
    has_current_human_approval,
    needs_human_review,
)


class CheckPrGateTests(unittest.TestCase):
    def test_requires_visible_decision_disclosure(self):
        body = "## Decisions and deviations\n\n<!-- placeholder only -->\n\n## Risk\n"
        self.assertIsNone(disclosed_decisions(body))
        self.assertEqual(
            disclosed_decisions(
                "## Decisions and deviations\n\nNone — implementation follows the issue exactly.\n"
            ),
            "None — implementation follows the issue exactly.",
        )

    def test_human_review_depends_only_on_escalation_label(self):
        self.assertFalse(needs_human_review({"labels": [{"name": "infrastructure"}]}))
        self.assertTrue(
            needs_human_review({"labels": [{"name": "needs-human-review"}]})
        )

    def test_approval_must_be_other_human_on_current_commit(self):
        pull_request = {
            "user": {"login": "author"},
            "head": {"sha": "current"},
        }
        reviews = [
            {
                "state": "APPROVED",
                "commit_id": "current",
                "user": {"login": "coderabbitai", "type": "Bot"},
            },
            {
                "state": "APPROVED",
                "commit_id": "old",
                "user": {"login": "friend", "type": "User"},
            },
        ]
        self.assertFalse(has_current_human_approval(pull_request, reviews))
        reviews.append(
            {
                "state": "APPROVED",
                "commit_id": "current",
                "user": {"login": "friend", "type": "User"},
            }
        )
        self.assertTrue(has_current_human_approval(pull_request, reviews))


if __name__ == "__main__":
    unittest.main()
