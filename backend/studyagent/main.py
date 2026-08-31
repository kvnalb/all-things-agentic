from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import ConnectionStatus, ProviderName
from .api.sources import router as sources_router
from .taskmaster.api import require_owner, router as taskmaster_router
from fastapi import Depends


app = FastAPI(title="StudyAgent", version="0.1.0")
app.include_router(taskmaster_router)
app.include_router(sources_router, dependencies=[Depends(require_owner)])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/status", response_model=list[ConnectionStatus])
def setup_status() -> list[ConnectionStatus]:
    return [ConnectionStatus(provider=provider) for provider in ProviderName]


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    assets = frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        candidate = frontend_dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
