# AGENTS.md

## Goal

Ship a reliable, judge-ready product quickly. Prefer the smallest clear change that proves working behavior. Do not add speculative abstractions, dependencies, or infrastructure.

## Workflow

- Never push directly to `main`.
- Use a short-lived `feat/`, `fix/`, `docs/`, or `chore/` branch.
- Create an issue for meaningful features, bugs, and infrastructure work. A PR is enough for trivial changes.
- Keep each PR focused on one outcome; do not mix features with unrelated refactors.
- Before merging, run `make check`, review the diff, and document manual verification.
- Agents may create issues, branches, commits, and PRs. They must not auto-merge.

## Review policy

CI and automated review are required on every PR. Human review is required only when automated review finds either:

- implementation drift from the linked issue, PRD, acceptance criteria, or explicit user intent; or
- a material decision, assumption, deviation, or suggestion implied by the diff that was not disclosed in chat and in the PR's `Decisions and deviations` section.

Do not require human review merely because a disclosed change touches infrastructure, security, persistence, dependencies, or external actions. Those changes still require explicit authorization, focused tests, and accurate disclosure.

PRs without `needs-human-review` may merge after CI and automated review pass. A PR with that label needs approval from a human other than its author on the current head commit.

## Decision reporting

- Never make a silent material decision. A decision is material if it changes scope, behavior, architecture, dependencies, security, data handling, external side effects, deployment, or the demo story.
- Report material choices in chat before implementing them, prefixed with `Decision:`, `Assumption:`, or `Suggestion:`.
- If intent is ambiguous or a choice would expand/change the requested outcome, pause for confirmation instead of choosing silently.
- Record every material decision, deviation, assumption, and unimplemented suggestion in the PR's `Decisions and deviations` section.
- Record decisions with lasting architectural or product impact in `docs/devlog.md`.
- `None — implementation follows the issue exactly.` is valid only when the diff contains no material choice beyond the stated acceptance criteria.

## Engineering rules

- Reuse existing code and platform features before adding new machinery.
- Keep orchestration, model reasoning, integrations, persistence, API, and UI concerns separate.
- Validate model-generated tool arguments before execution and expose only allowlisted tools.
- Give integrations typed or validated inputs, explicit timeouts, bounded retries, and clear failures.
- Make external writes idempotent so retries cannot create duplicate events, messages, or records.
- Persist state before and after consequential actions.
- Require approval for irreversible, destructive, costly, or sensitive actions.
- Use structured logs with a stable `run_id`; never log secrets or private student data.
- Non-trivial behavior needs a focused test. Bug fixes need a regression test.
- Never claim mocked or planned behavior is implemented or live.

## Secrets and data

- Never commit `.env`, credentials, service-account keys, tokens, private datasets, or unsanitized logs.
- Keep safe variable names and descriptions in `.env.example` only.
- Use synthetic or sanitized fixtures in tests and demos.
- Review screenshots and logs for private information before committing them.

## Evidence

For each meaningful or demo-worthy PR, append a short entry to `docs/devlog.md`:

- problem before the change;
- decision and why;
- behavior after the change;
- test, screenshot, or sanitized-log evidence;
- known limitation.

Update `docs/demo-script.md` when a reliable demo scenario changes. Do not journal typo fixes, formatting, or mechanical renames.

## Definition of done

- Acceptance criteria are met.
- `make check` passes.
- The primary path and relevant failure path were verified.
- No unrelated changes, secrets, or private data are present.
- README/architecture, devlog, and demo script are updated when affected.
- The PR discloses all material decisions, deviations, assumptions, and suggestions.
- The PR is small enough for another person or review agent to understand quickly.
