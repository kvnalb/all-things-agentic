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

CI and automated review are required on every PR. Human review is required when a change involves:

- ambiguous requirements or drift from the PRD;
- authentication, authorization, secrets, or private student data;
- agent tools, permissions, prompts that control actions, or model-generated arguments;
- external writes, deletion, retries, or idempotency;
- persistent state, schemas, migrations, or workflow states;
- Google Cloud IAM, deployment, networking, or production configuration;
- new runtime dependencies or hosted services;
- behavior or claims used in the hackathon demo;
- a diff too broad to verify confidently.

Low-risk documentation, UI, test, and narrowly scoped code changes may be merged after CI and automated review pass. Humans always make the final merge decision.

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
- The PR is small enough for another person or review agent to understand quickly.
