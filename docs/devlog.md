# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

## 2026-08-28 — Use conditional human review and decision disclosure

Issue: `#3`

- **Before:** Every PR needed one approval, even when CI and automated review found no intent drift.
- **Decision:** Require human review only for intent drift or material decisions missing from chat and the PR; enforce decision disclosure with a lightweight PR gate.
- **After:** Routine PRs can merge after CI and CodeRabbit, while `needs-human-review` conditionally requires a current human approval.
- **Evidence:** Unit tests for disclosure parsing and approval matching, plus the `risk-gate` GitHub check.
- **Limitation:** Automated review infers drift from written intent, so issues and PR descriptions must remain concrete.

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
