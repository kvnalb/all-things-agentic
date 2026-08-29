# StudyAgent

StudyAgent turns scattered academic sources into a source-linked Google
Calendar. The Fall 2026 hackathon build is a single-user workflow that connects
Canvas, Ed, public course sites, and uploaded syllabi, then imports safe
high-confidence events and sends uncertain items to review.

## Local development

Prerequisites: Python 3.12, `uv`, Node.js 22, and `pnpm`.

```bash
uv sync
pnpm --dir frontend install
uv run uvicorn studyagent.main:app --app-dir backend --reload
pnpm --dir frontend dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to FastAPI on port
8000.

## Checks

```bash
make check
```

The provider connectors and Google Cloud deployment are implemented in the
focused child issues linked from [issue #5](https://github.com/kvnalb/all-things-agentic/issues/5).
