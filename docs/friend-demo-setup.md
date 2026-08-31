# StudyAgent demo — quick setup

**Prereqs:** Python 3.12, uv, Node 22, pnpm, gcloud CLI

```bash
git clone <repo-url> && cd all-things-agentic
# add .env above

gcloud auth login
gcloud auth application-default login
gcloud config set project hackathon123456

uv sync
pnpm --dir frontend install && pnpm --dir frontend build
uv run uvicorn studyagent.main:app --app-dir backend --port 8080
```

Open http://localhost:8080

1. **Connect Google** (same email as `STUDYAGENT_ALLOWED_EMAIL`)
2. Finish **onboarding**
3. **Enable calendar writes** — DevTools → Cookies → copy `studyagent_session`, then:

```bash
curl -X POST http://localhost:8080/api/config/calendar-writes \
  -H "Content-Type: application/json" \
  -b "studyagent_session=PASTE" \
  -d '{"enabled": true}'
```

4. Click **Sync** — check the UI and Google Calendar → **StudyAgent — Fall 2026**
