# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

## 2026-08-30 — Effort calibration from owner feedback

Issue: `#5`

- **Before:** Effort estimates came only from the one-shot LLM call; there was no way to correct systematic under/over-estimation per course.
- **Decision:** Add a Firestore `calibration/owner` profile with EMA (exponential moving average — a running average that weights recent feedback more) multipliers per course and globally. Apply multipliers after `effort_agent`, before deterministic scheduling. Ranking formulas unchanged.
- **After:** Dashboard tasks expose quick ratings plus optional actual hours; `POST /api/feedback` updates multipliers; next sync budgets adjusted hours and injects recent examples into the effort prompt.
- **Evidence:** `tests/test_calibration.py`, `make check`.
- **Limitation:** Syllabus difficulty is not yet user-calibratable; feedback does not auto re-sync the calendar until the next manual or scheduled sync.

## 2026-08-29 — Replace the reimplementation with a verbatim donor port

Issue: `#5`

- **Before:** The first “donor port” reimplemented scheduling with `planning.py`, `extraction.py`, and a slim service layer. It dropped syllabus grounding, difficulty multipliers, the 7-question config semantics, `TASK_LIST` artifacts, donor daily tiers, and the reminder-agent path.
- **Decision:** Copy co-submitter modules from `9120d1c` into `backend/studyagent/taskmaster/donor/` and patch only persistence/auth boundaries (`store.py`, Secret Manager Canvas token, Vertex syllabus analysis, idempotent `CalendarWriter.sync_donor_blocks`). Keep the existing GCP shell unchanged.
- **After:** `TaskmasterService.sync_semester()` runs donor `analyze_all_courses` → ADK effort graph per task → donor `rebuild_calendar_and_brief` → `write_task_list` → `build_daily_view`, with Firestore artifacts replacing local JSON files.
- **Evidence:** `make check` (49 tests), donor graph/scoring/calendar-binding regressions, and service wiring in `service.py`/`api.py`.
- **Limitation:** One manual re-sync is required to replace low-quality calendar blocks from the old planner; live Fall ’26 verification still depends on owner GCP credentials.

## 2026-08-29 — Port the proven Taskmaster into the GCP shell

Issue: `#5`

- **Before:** The canonical repo had safe source scaffolding but no complete student workflow; a custom integration was duplicating a co-submitter’s working agent.
- **Decision:** Make co-submitter commit `9120d1c` the behavioral source of truth. Port onboarding, effort estimation, scoring, calendar planning, colors, daily tiers, and activity while replacing local files and calendar rebuilds with Secret Manager, Firestore, and stable bindings.
- **After:** One Cloud Run service exposes owner setup, real Canvas discovery, source ingestion, manual/hourly sync, task/daily/activity views, and a corrected ADK 2 graph.
- **Evidence:** Donor-parity and graph regression tests, `make check`, Cloud Run revision `studyagent-00004-6rp`, owner-guard `401`, and live discovery of seven Fall ’26 Canvas shells.
- **Limitation:** Google OAuth consent, Calendar idempotency, and scheduled-run evidence must pass before submission.

## 2026-08-28 — Make credential setup explicit and reproducible

Issue: `#13`

- **Before:** Canvas and Google Cloud prerequisites were implicit, making it unclear which tokens, APIs, OAuth scopes, secrets, and runtime roles the real demo required.
- **Decision:** Document one owner-only setup using a Canvas personal token, Vertex AI, private source storage, Calendar-only OAuth, Secret Manager, and a least-privilege Cloud Run identity; exclude Gmail.
- **After:** `docs/setup_guide.md` provides ordered console steps, copyable commands, safe secret handling, exact permissions, and non-secret readiness checks.
- **Evidence:** `make check` passed with 37 backend tests and the production frontend build.
- **Limitation:** The guide provisions credentials and infrastructure; live connector verification still occurs in issue `#8` without recording private values.

## 2026-08-28 — Bound source ingestion and model extraction

Issue: `#9`

- **Before:** Course pages and syllabus files had no safe ingestion path or constrained bridge into Gemini.
- **Decision:** Reject redirects and non-public network destinations, retain immutable raw and normalized revisions, and separate a versioned tool-free Gemini prompt from ADK execution and deterministic validation. Model-extracted events always require review.
- **After:** Public URLs and PDF/HTML/Markdown/text uploads are bounded and privately persisted with reusable revision and extraction provenance rather than discarded after event extraction.
- **Evidence:** Focused SSRF/deadline, content-signature, revision identity, partial persistence, prompt boundary, schema, timezone, recurrence, and manual-review tests included in `make check`.
- **Limitation:** Live Cloud Storage, Firestore, and Vertex AI verification is deferred to issue `#8`. DNS is validated before connection but not pinned through TLS; production multi-user egress should enforce destination IP policy at connect time.

## 2026-08-28 — Establish one deployable application boundary

Issue: `#6`

- **Before:** The repository contained planning and workflow documents but no runnable product scaffold or shared contracts.
- **Decision:** Serve a React/Vite interface and FastAPI/ADK backend from one Cloud Run container, with strict Pydantic contracts between probabilistic extraction and deterministic actions.
- **After:** The application has a buildable visual shell, health/setup APIs, validated domain contracts, and focused backend/frontend checks.
- **Evidence:** `make check` (7 tests plus frontend production build), a successful Docker build, and live container checks for `/api/health` and the compiled frontend.
- **Limitation:** Provider connections and imports remain explicitly disabled until their focused issues land.

## 2026-08-28 — Use a lightweight agent-merge workflow

Issue: `#3`

- **Before:** Every PR needed one approval, and the first conditional-review design added custom process code before product code.
- **Decision:** Let agents merge unambiguous PRs after current-head CI success; keep CodeRabbit asynchronous and advisory while issues preserve intent and humans handle ambiguity or unauthorized consequential actions.
- **After:** Preflight chat, focused PR evidence, deterministic CI, and optional CodeRabbit findings provide safeguards without blanket peer approval, a custom risk gate, or review-service latency.
- **Evidence:** `docs/workflow.md`, repository templates, CodeRabbit policy, `make check`, and protected-branch settings.
- **Limitation:** Advisory findings can arrive after merge; valid late findings require a focused follow-up.

## 2026-08-27 — Standardize on CodeRabbit review automation

Issue: `#3`

- **Before:** The repository included an unused Pullfrog workflow while the team had selected CodeRabbit; CI also used a deprecated Node.js 20-based Checkout action.
- **Decision:** Use CodeRabbit alone, with quiet reviews, automatic risk labels, and `AGENTS.md` as the shared review standard.
- **After:** Pullfrog is removed, Checkout uses v7, and CodeRabbit can approve routine changes while escalating substantive risk.
- **Evidence:** `make check`, YAML parsing, and GitHub Actions.
- **Limitation:** CodeRabbit must already be installed and authorized for the repository.

## Entry template

### YYYY-MM-DD — Change title

Issue/PR: `#issue` / `#pr`

- **Before:**
- **Decision:**
- **After:**
- **Evidence:**
- **Limitation:**
