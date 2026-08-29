from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from google.api_core.exceptions import AlreadyExists, PreconditionFailed
from google.cloud import firestore, storage
from pypdf import PdfReader

from studyagent.models import IngestedSource, Source, SourceKind, SourceRevision


MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 500_000
MAX_PDF_PAGES = 200
FETCH_TIMEOUT_SECONDS = 10.0
PARSER_TIMEOUT_SECONDS = 15.0
PARSER_VERSION = "source-parser-v1"

logger = logging.getLogger(__name__)

MEDIA_TYPES_BY_SUFFIX = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}
SUPPORTED_MEDIA_TYPES = {
    "application/pdf",
    "application/xhtml+xml",
    "text/html",
    "text/markdown",
    "text/plain",
}


class SourceIngestionError(ValueError):
    """A source cannot be ingested safely."""


class UnsafeUrlError(SourceIngestionError):
    pass


class OversizedSourceError(SourceIngestionError):
    pass


class UnsupportedSourceError(SourceIngestionError):
    pass


@dataclass(frozen=True)
class FetchedDocument:
    content: bytes
    media_type: str


@dataclass(frozen=True)
class ParsedDocument:
    content: bytes
    media_type: str
    text: str


Resolver = Callable[[str], Awaitable[Sequence[str]]]


async def resolve_addresses(hostname: str) -> Sequence[str]:
    def resolve() -> list[str]:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        return sorted({record[4][0] for record in records})

    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            return await asyncio.to_thread(resolve)
    except TimeoutError as exc:
        raise UnsafeUrlError("source hostname resolution timed out") from exc
    except socket.gaierror as exc:
        raise UnsafeUrlError("source hostname could not be resolved") from exc


def _require_public_addresses(addresses: Sequence[str]) -> None:
    if not addresses:
        raise UnsafeUrlError("source hostname did not resolve")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrlError("source hostname returned an invalid address") from exc
        if not parsed.is_global:
            raise UnsafeUrlError("source hostname resolves to a non-public address")


def _media_type(value: str | None, filename: str) -> str:
    header_type = (value or "").split(";", 1)[0].strip().lower()
    suffix_type = MEDIA_TYPES_BY_SUFFIX.get(Path(filename).suffix.lower())
    if header_type in SUPPORTED_MEDIA_TYPES:
        return "text/html" if header_type == "application/xhtml+xml" else header_type
    if header_type in {"", "application/octet-stream"} and suffix_type:
        return suffix_type
    raise UnsupportedSourceError("source must be PDF, HTML, Markdown, or plain text")


class SafeUrlFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = resolve_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchedDocument:
        parsed = httpx.URL(url)
        if parsed.scheme != "https" or not parsed.host:
            raise UnsafeUrlError("source URL must use public HTTPS")
        if parsed.userinfo:
            raise UnsafeUrlError("source URL cannot contain credentials")
        if parsed.port not in {None, 443}:
            raise UnsafeUrlError("source URL must use the standard HTTPS port")

        try:
            async with asyncio.timeout(self._timeout_seconds):
                await _validate_host(parsed.host, self._resolver)
        except TimeoutError as exc:
            raise UnsafeUrlError("source hostname resolution timed out") from exc
        for attempt in range(2):
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    return await self._fetch_once(parsed)
            except (TimeoutError, httpx.TransportError) as exc:
                if attempt == 1:
                    raise SourceIngestionError("source could not be fetched") from exc
        raise AssertionError("unreachable")

    async def _fetch_once(self, url: httpx.URL) -> FetchedDocument:
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            transport=self._transport,
            trust_env=False,
            headers={"User-Agent": "StudyAgent/0.1 syllabus-fetcher"},
        ) as client:
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    raise UnsafeUrlError("redirecting source URLs are not accepted")
                if response.status_code in {502, 503, 504}:
                    raise httpx.ReadError(
                        "temporary upstream failure", request=response.request
                    )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SourceIngestionError(
                        "source returned an unsuccessful response"
                    ) from exc

                declared_size = response.headers.get("content-length")
                if declared_size and declared_size.isdigit():
                    if int(declared_size) > MAX_SOURCE_BYTES:
                        raise OversizedSourceError("source exceeds the 10 MB limit")

                media_type = _media_type(
                    response.headers.get("content-type"),
                    url.path,
                )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise OversizedSourceError("source exceeds the 10 MB limit")
                    chunks.append(chunk)
                return FetchedDocument(content=b"".join(chunks), media_type=media_type)


async def _validate_host(hostname: str, resolver: Resolver) -> None:
    try:
        direct_address = ipaddress.ip_address(hostname)
    except ValueError:
        addresses = await resolver(hostname)
    else:
        addresses = [str(direct_address)]
    _require_public_addresses(addresses)


class SourceParser:
    def parse(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str | None,
    ) -> ParsedDocument:
        if len(content) > MAX_SOURCE_BYTES:
            raise OversizedSourceError("source exceeds the 10 MB limit")
        resolved_type = _media_type(media_type, filename)
        has_pdf_signature = b"%PDF-" in content[:1024]
        if has_pdf_signature:
            resolved_type = "application/pdf"
        elif resolved_type == "application/pdf":
            raise UnsupportedSourceError("PDF signature is missing")

        if resolved_type == "application/pdf":
            text = self._parse_pdf(content)
        elif resolved_type == "text/html":
            text = self._parse_html(content)
        else:
            text = content.decode("utf-8", errors="replace")

        normalized = "\n".join(
            line.strip() for line in text.splitlines() if line.strip()
        )
        if not normalized:
            raise UnsupportedSourceError("source contains no extractable text")
        if len(normalized) > MAX_EXTRACTED_CHARACTERS:
            raise OversizedSourceError("source contains too much extracted text")
        return ParsedDocument(
            content=content, media_type=resolved_type, text=normalized
        )

    @staticmethod
    def _parse_html(content: bytes) -> str:
        soup = BeautifulSoup(content, "html.parser")
        for element in soup(["script", "style", "noscript", "template"]):
            element.decompose()
        return soup.get_text("\n")

    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise UnsupportedSourceError("encrypted PDFs are not supported")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise OversizedSourceError("PDF exceeds the 200-page limit")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except (OversizedSourceError, UnsupportedSourceError):
            raise
        except Exception as exc:
            raise UnsupportedSourceError("PDF could not be parsed") from exc


class SnapshotStore(Protocol):
    async def save(
        self,
        source: Source,
        revision: SourceRevision,
        *,
        raw_content: bytes,
        normalized_text: str,
    ) -> IngestedSource: ...


class GoogleSnapshotStore:
    def __init__(self, *, project: str, bucket: str) -> None:
        self._bucket_name = bucket
        self._storage = storage.Client(project=project)
        self._firestore = firestore.Client(project=project)

    async def save(
        self,
        source: Source,
        revision: SourceRevision,
        *,
        raw_content: bytes,
        normalized_text: str,
    ) -> IngestedSource:
        return await asyncio.to_thread(
            self._save_sync,
            source,
            revision,
            raw_content,
            normalized_text,
        )

    def _save_sync(
        self,
        source: Source,
        revision: SourceRevision,
        raw_content: bytes,
        normalized_text: str,
    ) -> IngestedSource:
        source_document = self._firestore.collection("sources").document(source.id)
        revision_document = source_document.collection("revisions").document(
            revision.id
        )
        prefix = f"source-snapshots/{source.id}/{revision.id}"
        raw_name = f"{prefix}/raw"
        text_name = f"{prefix}/normalized.txt"
        bucket = self._storage.bucket(self._bucket_name)
        try:
            source_document.set(
                {
                    **source.model_dump(mode="json", exclude_none=True),
                    "state": "uploading",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
                timeout=15,
            )
            try:
                revision_document.create(
                    {
                        **revision.model_dump(mode="json"),
                        "state": "uploading",
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    timeout=15,
                )
            except AlreadyExists:
                revision_document.set(
                    {
                        "state": "uploading",
                        "last_run_id": revision.run_id,
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                    timeout=15,
                )
            self._upload_if_absent(
                bucket.blob(raw_name), raw_content, revision.media_type
            )
            self._upload_if_absent(
                bucket.blob(text_name),
                normalized_text.encode("utf-8"),
                "text/plain; charset=utf-8",
            )
            stored_revision = revision.model_copy(
                update={
                    "object_ref": f"gs://{self._bucket_name}/{raw_name}",
                    "normalized_ref": f"gs://{self._bucket_name}/{text_name}",
                }
            )
            stored_source = source.model_copy(
                update={
                    "current_revision_id": revision.id,
                    "current_revision_fetched_at": revision.fetched_at,
                }
            )
            revision_document.set(
                {
                    "object_ref": stored_revision.object_ref,
                    "normalized_ref": stored_revision.normalized_ref,
                    "state": "ready",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
                timeout=15,
            )
            current_source = self._advance_current_revision(
                source_document=source_document,
                stored_source=stored_source,
                revision=revision,
            )
            return IngestedSource(source=current_source, revision=stored_revision)
        except Exception:
            try:
                revision_document.set(
                    {"state": "error", "updated_at": firestore.SERVER_TIMESTAMP},
                    merge=True,
                    timeout=15,
                )
                source_document.set(
                    {"state": "error", "updated_at": firestore.SERVER_TIMESTAMP},
                    merge=True,
                    timeout=15,
                )
            except Exception:
                logger.exception(
                    "snapshot error-state write failed",
                    extra={"run_id": revision.run_id, "source_id": source.id},
                )
            raise

    def _advance_current_revision(
        self,
        *,
        source_document: firestore.DocumentReference,
        stored_source: Source,
        revision: SourceRevision,
    ) -> Source:
        transaction = self._firestore.transaction()

        @firestore.transactional
        def update_current(transaction: firestore.Transaction) -> Source:
            snapshot = source_document.get(transaction=transaction)
            values = snapshot.to_dict() or {}
            current_fetched_at = values.get("current_revision_fetched_at")
            if isinstance(current_fetched_at, str):
                try:
                    current_fetched_at = datetime.fromisoformat(current_fetched_at)
                except ValueError as exc:
                    raise SourceIngestionError(
                        "stored source revision timestamp is invalid"
                    ) from exc
            if (
                current_fetched_at is None
                or revision.fetched_at >= current_fetched_at
            ):
                transaction.set(
                    source_document,
                    {
                        **stored_source.model_dump(mode="json", exclude_none=True),
                        "state": "ready",
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return stored_source
            return stored_source.model_copy(
                update={
                    "current_revision_id": values.get("current_revision_id"),
                    "current_revision_fetched_at": values.get(
                        "current_revision_fetched_at"
                    ),
                }
            )

        return update_current(transaction)

    @staticmethod
    def _upload_if_absent(blob: storage.Blob, content: bytes, media_type: str) -> None:
        try:
            blob.upload_from_string(
                content,
                content_type=media_type,
                timeout=15,
                if_generation_match=0,
            )
        except PreconditionFailed:
            # The object name includes its content hash, so an existing object is
            # the successful result of an earlier attempt.
            pass


class SourceIngestionService:
    def __init__(
        self,
        *,
        store: SnapshotStore,
        fetcher: SafeUrlFetcher | None = None,
        parser: SourceParser | None = None,
        parser_timeout_seconds: float = PARSER_TIMEOUT_SECONDS,
    ) -> None:
        self._store = store
        self._fetcher = fetcher or SafeUrlFetcher()
        self._parser = parser or SourceParser()
        self._parser_timeout_seconds = parser_timeout_seconds

    async def add_url(
        self, *, course_id: str, label: str, url: str
    ) -> IngestedSource:
        canonical_url = str(httpx.URL(url).copy_with(fragment=None))
        fetched = await self._fetcher.fetch(canonical_url)
        parsed = await self._parse(
            content=fetched.content,
            filename=httpx.URL(canonical_url).path,
            media_type=fetched.media_type,
        )
        source, revision = self._new_source_revision(
            course_id=course_id,
            label=label,
            kind=SourceKind.URL,
            parsed=parsed,
            url=canonical_url,
        )
        return await self._store.save(
            source,
            revision,
            raw_content=parsed.content,
            normalized_text=parsed.text,
        )

    async def add_upload(
        self,
        *,
        course_id: str,
        filename: str,
        content: bytes,
        media_type: str | None,
    ) -> IngestedSource:
        parsed = await self._parse(
            content=content,
            filename=filename,
            media_type=media_type,
        )
        source, revision = self._new_source_revision(
            course_id=course_id,
            label=filename,
            kind=SourceKind.UPLOAD,
            parsed=parsed,
        )
        return await self._store.save(
            source,
            revision,
            raw_content=parsed.content,
            normalized_text=parsed.text,
        )

    async def _parse(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str | None,
    ) -> ParsedDocument:
        try:
            async with asyncio.timeout(self._parser_timeout_seconds):
                return await asyncio.to_thread(
                    self._parser.parse,
                    content=content,
                    filename=filename,
                    media_type=media_type,
                )
        except TimeoutError as exc:
            raise SourceIngestionError("source parsing timed out") from exc

    @staticmethod
    def _new_source_revision(
        *,
        course_id: str,
        label: str,
        kind: SourceKind,
        parsed: ParsedDocument,
        url: str | None = None,
    ) -> tuple[Source, SourceRevision]:
        content_hash = hashlib.sha256(parsed.content).hexdigest()
        source_identity = "\0".join([course_id, kind.value, url or label]).encode()
        source_id = hashlib.sha256(source_identity).hexdigest()[:24]
        revision_identity = f"{source_id}\0{content_hash}".encode()
        revision_id = hashlib.sha256(revision_identity).hexdigest()[:24]
        source = Source(
            id=source_id,
            course_id=course_id,
            kind=kind,
            label=label,
            url=url,
        )
        revision = SourceRevision(
            id=revision_id,
            source_id=source_id,
            run_id=uuid4().hex,
            content_hash=content_hash,
            media_type=parsed.media_type,
            fetched_at=datetime.now(UTC),
            parser_version=PARSER_VERSION,
        )
        return source, revision
