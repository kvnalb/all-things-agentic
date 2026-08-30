# Four-minute Taskmaster demo

Use sanitized names and counts. Start logged in with the dedicated calendar and dashboard open.

## 0:00–0:30 — outcome first

- Show six scattered Fall ’26 courses, the StudyAgent calendar, and today’s ranked task view.
- Say: “StudyAgent manages my semester continuously. It notices course changes, decides what matters, and updates my work plan without a chat prompt.”

## 0:30–1:20 — real inputs and bounded agent

- Show Canvas connected, Data 101 and Math 110 URLs, and a retained syllabus.
- Trigger **Sync now** and show sanitized created/updated/skipped/submitted counts.
- Explain that ADK/Gemini estimates effort and extracts evidenced facts while deterministic code controls priority and Calendar writes.

## 1:20–2:15 — consequential action

- Open one source-linked `[DUE]` event and its colored study blocks.
- Show the same task in the daily HIGH/MEDIUM/LOW view with its recommended start date.
- Point out the separate `StudyAgent — Fall 2026` calendar.

## 2:15–2:50 — long-running and idempotent

- Show the hourly Cloud Scheduler job and a Firestore `runs` record triggered by `scheduler`.
- Run an unchanged sync and show `created: 0`, `updated: 0`, and nonzero `skipped`.
- Use the sanitized changed-deadline fixture to show one existing event patched.

## 2:50–3:30 — architecture and cloud proof

- Show `docs/architecture.md`, the Cloud Run revision, a sanitized ADK/Vertex log with `run_id`, and Firestore tasks/bindings/runs.
- State that Cloud Run scales to zero and Firestore preserves semester state.

## 3:30–4:00 — close

- Return to the finished calendar and daily dashboard.
- Say: “A semester is a months-long task. StudyAgent wakes, observes, reasons, acts idempotently, records what happened, and goes dormant again.”

## Before recording

- `make check` passes on the recorded revision.
- Real Google OAuth and Canvas connections succeed.
- Six academic courses selected; CDSS Career Seminar excluded.
- Data 101, Math 110, and one syllabus revision exist privately.
- An unchanged second sync creates zero duplicates.
- A scheduler-triggered run exists.
- Screenshots and logs contain no tokens, source bodies, or private descriptions.
