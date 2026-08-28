#!/usr/bin/env python3
"""Require decision disclosure, and human approval only for escalated PRs."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request


DECISIONS_HEADING = re.compile(
    r"^## Decisions and deviations\s*$\n(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def disclosed_decisions(body: str) -> str | None:
    """Return visible decision disclosure, or None when missing/empty."""
    match = DECISIONS_HEADING.search(body or "")
    if not match:
        return None
    visible = HTML_COMMENT.sub("", match.group("body")).strip()
    return visible or None


def needs_human_review(pull_request: dict) -> bool:
    return any(
        label.get("name") == "needs-human-review"
        for label in pull_request.get("labels", [])
    )


def has_current_human_approval(pull_request: dict, reviews: list[dict]) -> bool:
    author = pull_request["user"]["login"]
    head_sha = pull_request["head"]["sha"]
    return any(
        review.get("state") == "APPROVED"
        and review.get("commit_id") == head_sha
        and review.get("user", {}).get("type") == "User"
        and review.get("user", {}).get("login") != author
        for review in reviews
    )


def fetch_reviews(repository: str, number: int, token: str) -> list[dict]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/pulls/{number}/reviews",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def main() -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as event_file:
        event = json.load(event_file)

    pull_request = event["pull_request"]
    if not disclosed_decisions(pull_request.get("body") or ""):
        print(
            "PR must contain a non-empty '## Decisions and deviations' section.",
            file=sys.stderr,
        )
        return 1

    if not needs_human_review(pull_request):
        print("decision disclosure present; no human review escalation")
        return 0

    reviews = fetch_reviews(
        os.environ["GITHUB_REPOSITORY"],
        pull_request["number"],
        os.environ["GITHUB_TOKEN"],
    )
    if not has_current_human_approval(pull_request, reviews):
        print(
            "needs-human-review requires approval from another human on the current commit.",
            file=sys.stderr,
        )
        return 1

    print("current human approval found for escalated PR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
