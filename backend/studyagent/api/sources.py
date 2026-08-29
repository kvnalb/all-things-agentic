from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import AnyHttpUrl, BaseModel, Field

from studyagent.connectors.sources import (
    MAX_SOURCE_BYTES,
    GoogleSnapshotStore,
    OversizedSourceError,
    SourceIngestionError,
    SourceIngestionService,
)
from studyagent.models import IngestedSource


router = APIRouter(prefix="/api/sources", tags=["sources"])


class UrlSourceRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl


@lru_cache
def get_source_service() -> SourceIngestionService:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket = os.environ.get("STUDYAGENT_SOURCE_BUCKET")
    if not project or not bucket:
        raise RuntimeError("source storage is not configured")
    return SourceIngestionService(
        store=GoogleSnapshotStore(project=project, bucket=bucket)
    )


SourceService = Annotated[SourceIngestionService, Depends(get_source_service)]


@router.post("/url", response_model=IngestedSource, status_code=status.HTTP_201_CREATED)
async def add_url(
    request: UrlSourceRequest, service: SourceService
) -> IngestedSource:
    try:
        return await service.add_url(
            course_id=request.course_id,
            label=request.label,
            url=str(request.url),
        )
    except OversizedSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except SourceIngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/upload", response_model=IngestedSource, status_code=status.HTTP_201_CREATED
)
async def add_upload(
    service: SourceService,
    course_id: Annotated[str, Form(min_length=1, max_length=200)],
    file: Annotated[UploadFile, File()],
) -> IngestedSource:
    content = await file.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="source exceeds the 10 MB limit",
        )
    try:
        return await service.add_upload(
            course_id=course_id,
            filename=file.filename or "uploaded-source.txt",
            content=content,
            media_type=file.content_type,
        )
    except OversizedSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except SourceIngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
