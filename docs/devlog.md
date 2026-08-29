# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

## 2026-08-28 — Keep Ed optional and staff-only

Issue: `#11`

- **Before:** StudyAgent had no Ed connection path, so course announcements and staff logistics could not contribute source evidence.
- **Decision:** Use a small read-only adapter with conservative course matching, explicit manual overrides, bounded pagination/retries, and a fail-closed staff/public thread filter.
- **After:** A token can validate through `/api/user`, active courses can be mapped to Canvas courses, and only public staff announcements plus pinned/recent staff threads are returned; Ed errors remain connector-local.
- **Evidence:** Sanitized fixtures and focused tests cover active-course discovery, overrides, content filtering, token-safe errors, and successful orchestration.
- **Limitation:** Ed's API is undocumented/beta; the adapter intentionally accepts only the tested user/course/thread response shapes and remains optional.

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
