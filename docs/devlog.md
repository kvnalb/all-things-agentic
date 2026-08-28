# Engineering devlog

Keep entries short and limited to meaningful or demo-worthy decisions.

### 2026-08-27 — Standardize on CodeRabbit review automation

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
