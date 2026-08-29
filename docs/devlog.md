# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

## 2026-08-28 — Bound Google access to an app-created calendar

Issue: `#13`

- **Before:** The setup shell could not connect Google, retain offline access, recover its calendar, or prove Gmail send safely.
- **Decision:** Request only identity, `calendar.app.created`, and `gmail.send`; require a refresh token; store credentials through an injected Secret Manager boundary; and recover the dedicated calendar by persisted ID because the narrow scope cannot list every user calendar.
- **After:** A tested OAuth service validates one-time state, fails closed on incomplete grants, creates or recovers `StudyAgent — Fall 2026`, and sends an explicit test email only to the connected identity.
- **Evidence:** Focused fakes verify exact scopes, offline consent, token redaction, invalid/replayed/expired state, missing refresh tokens, calendar idempotency, and explicit email send without a live account.
- **Limitation:** Google SDK, Secret Manager/Firestore adapters, router composition, OAuth credentials, and live Cloud Run verification remain integration work; External/Testing refresh tokens expire after seven days under current Google policy.

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
