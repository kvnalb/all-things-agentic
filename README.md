# StudyAgent

StudyAgent is a long-running academic Taskmaster. It watches Canvas and course
sources, estimates effort with a bounded ADK 2/Gemini workflow, deterministically
prioritizes work, and keeps a dedicated Google Calendar and daily task view
current throughout a semester.

The Fall 2026 submission is deployed on Cloud Run and uses Vertex AI,
Firestore, Cloud Storage, Secret Manager, Cloud Scheduler, Canvas, and Google
Calendar. It is an owner-only application—not a chatbot and not a mock calendar.

## What it does

- Discovers real Fall ’26 Canvas courses and excludes teaching roles.
- Retains submitted work but does not schedule it.
- Reads structured Canvas deadlines, rich-text syllabi, syllabus files, and attached public course websites.
- Uses Gemini only for bounded effort estimation and grounded source extraction; priority and scheduling remain deterministic code.
- Creates source-linked deadline events and color-coded study blocks in one dedicated calendar.
- Creates, patches, or skips events by stable keys, so reruns do not duplicate them.
- Exposes onboarding preferences, persistent tasks, recommended start dates, daily priority tiers, and activity history.
- Runs from the same sync function when triggered manually or hourly.

## Architecture

See [system and agent design](docs/architecture.md). Runtime continuity lives
in Firestore; Cloud Run can scale to zero between Cloud Scheduler wakes.

```text
Canvas + course sources → Cloud Run → ADK 2 + Vertex Gemini
                       → deterministic planner → Google Calendar
                       → Firestore tasks/bindings/runs → React dashboard
```

## Repository map

- `backend/studyagent/taskmaster/` — donor-port agent, scoring, scheduling, Canvas, OAuth, Calendar, Firestore, and sync.
- `backend/studyagent/connectors/` — bounded source ingestion and extraction.
- `frontend/` — two-screen setup and daily dashboard.
- `tests/` — contracts, source safety, donor parity, and agent regressions.
- `docs/` — setup, architecture, devlog, and four-minute demo script.

Taskmaster behavior is ported from co-submitter Anayaa Jogani’s working agent
at commit `9120d1c`; Google sample-derived files retain their Apache 2.0 notice.
Local credential files and generated student data are intentionally not copied.

## Run and verify

Prerequisites: Python 3.12, `uv`, Node.js 22, and `pnpm`. Complete
[credential and GCP setup](docs/setup_guide.md), then:

```bash
uv sync
pnpm --dir frontend install
make check
uv run uvicorn studyagent.main:app --app-dir backend --port 8080
```

The deployed container serves FastAPI and the compiled React frontend.
Provider tokens remain in Secret Manager.

## Hackathon proof

The [demo script](docs/demo-script.md) shows a manual wake, a Calendar patch,
an unchanged rerun with zero duplicates, persisted Firestore run state, and the
hourly Scheduler job. Private course bodies, tokens, and OAuth payloads never
belong in screenshots or repository fixtures.
