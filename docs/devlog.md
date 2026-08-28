# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

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
