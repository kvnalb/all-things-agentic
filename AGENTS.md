# AGENTS.md

## Goal

Ship a reliable, judge-ready product quickly. Prefer the smallest clear change that proves working behavior. Do not add speculative abstractions, dependencies, or infrastructure.

## Workflow

- Never push directly to `main`.
- Use a short-lived `feat/`, `fix/`, `docs/`, or `chore/` branch.
- Create an issue for meaningful features, bugs, and infrastructure work. A PR is enough for trivial changes.
- Treat the linked issue as the canonical, reviewable statement of intent. When chat materially changes the requested outcome, constraints, or acceptance criteria, update the issue before continuing.
- Before editing, post a concise chat preflight using `Intent:`, `Plan:`, `Material decisions/assumptions:`, and `Will pause if:`. Continue without waiting when the intent is unambiguous.
- Keep each PR focused on one outcome; do not mix features with unrelated refactors.
- Before merging, run `make check`, review the diff, and document manual verification.
- Agents may create issues, branches, commits, PRs, and merge routine PRs after every merge gate below passes.

## Review policy

CI and CodeRabbit review are required on every PR. Human involvement is required only for:

- ambiguous intent or implementation drift from the linked issue, PRD, acceptance criteria, or explicit user direction;
- a material decision, assumption, or deviation implied by the diff but not disclosed in chat and the PR;
- a destructive, costly, sensitive, or externally consequential action that lacks explicit authorization; or
- a CodeRabbit outage or pending review lasting more than ten minutes.

Do not require human review merely because an authorized and disclosed change touches infrastructure, security, persistence, dependencies, or external actions. Require focused tests and accurate disclosure.

A PR is eligible for agent merge only when `check` and `CodeRabbit` succeed on the current head commit, the PR is not a draft, all review conversations are resolved, and `needs-human-review` is absent. If CodeRabbit remains pending for ten minutes, the agent must report the outage and stop; only a human may explicitly override it.

## Decision reporting

- Never make a silent material decision. A decision is material if it changes scope, behavior, architecture, dependencies, security, data handling, external side effects, deployment, or the demo story.
- Report newly discovered material choices in chat immediately, prefixed with `Decision:`, `Assumption:`, or `Suggestion:`.
- If intent is ambiguous or a choice would expand/change the requested outcome, pause for confirmation instead of choosing silently.
- Record material decisions, deviations, and assumptions in the PR's `Decisions and assumptions` section.
- Record decisions with lasting architectural or product impact in `docs/devlog.md`.
- `None — implementation follows the issue exactly.` is valid only when the diff contains no material choice beyond the stated acceptance criteria.

## CodeRabbit triage

- Inspect every substantive CodeRabbit finding; never apply suggestions blindly.
- Fix valid findings, add or update a focused test when appropriate, and rerun `make check`.
- Reply to invalid findings with a concrete, verified rationale.
- After any new commit, wait for CI and CodeRabbit to evaluate the new head. Stale results never authorize a merge.
- Before handoff or merge, summarize findings fixed, rejected with rationale, and unresolved.

## Merge procedure

- Recheck the current head, required statuses, labels, draft state, and unresolved conversations immediately before merging.
- Never use administrator bypass. A bypass is reserved for an explicit human decision during a CodeRabbit outage.
- Post a concise handoff containing `Delivered`, `Intent changes`, `Decisions`, `Verification`, `CodeRabbit`, `Watch-outs`, and `Try it`.
- If every gate passes, squash-merge the PR and delete its branch.

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
- The PR discloses all material decisions, deviations, and assumptions.
- CI and CodeRabbit pass on the current head, and review conversations are resolved.
- The PR is small enough for another person or review agent to understand quickly.
