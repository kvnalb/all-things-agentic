import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from studyagent.api.sources import get_source_service, router
from studyagent.connectors.sources import (
    MAX_SOURCE_BYTES,
    OversizedSourceError,
    SafeUrlFetcher,
    SnapshotStore,
    SourceIngestionService,
    SourceParser,
    UnsafeUrlError,
    UnsupportedSourceError,
)
from studyagent.extraction import (
    MAX_MODEL_SOURCE_CHARACTERS,
    AdkGeminiModel,
    EventExtractor,
    ExtractionError,
)
from studyagent.models import Source, SourceKind


async def public_resolver(_: str) -> Sequence[str]:
    return ["8.8.8.8"]


async def private_resolver(_: str) -> Sequence[str]:
    return ["127.0.0.1"]


class MemorySnapshotStore(SnapshotStore):
    def __init__(self) -> None:
        self.saved: list[tuple[Source, bytes, str, str]] = []

    async def save(
        self,
        source: Source,
        *,
        raw_content: bytes,
        normalized_text: str,
        media_type: str,
    ) -> Source:
        self.saved.append((source, raw_content, normalized_text, media_type))
        return source.model_copy(update={"object_ref": f"memory://{source.id}"})


class FakeModel:
    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.output


class SourceParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SourceParser()

    def test_html_removes_executable_and_hidden_content(self) -> None:
        parsed = self.parser.parse(
            content=b"<main>Exam: Sep 10</main><script>steal()</script><style>x{}</style>",
            filename="syllabus.html",
            media_type="text/html; charset=utf-8",
        )
        self.assertEqual(parsed.text, "Exam: Sep 10")

    def test_supported_upload_can_be_inferred_from_suffix(self) -> None:
        parsed = self.parser.parse(
            content=b"# Schedule\nHomework due Friday",
            filename="syllabus.md",
            media_type="application/octet-stream",
        )
        self.assertEqual(parsed.media_type, "text/markdown")

    def test_pdf_text_is_extracted(self) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (Midterm September 10) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        buffer = BytesIO()
        writer.write(buffer)

        parsed = self.parser.parse(
            content=buffer.getvalue(),
            filename="syllabus.pdf",
            media_type="application/pdf",
        )
        self.assertIn("Midterm September 10", parsed.text)

    def test_unsupported_or_oversized_upload_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedSourceError):
            self.parser.parse(
                content=b"binary",
                filename="syllabus.docx",
                media_type="application/octet-stream",
            )
        with self.assertRaises(OversizedSourceError):
            self.parser.parse(
                content=b"x" * (MAX_SOURCE_BYTES + 1),
                filename="syllabus.txt",
                media_type="text/plain",
            )


class SafeUrlFetcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_a_small_supported_public_source(self) -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<p>Course schedule</p>",
            )
        )
        result = await SafeUrlFetcher(
            resolver=public_resolver,
            transport=transport,
        ).fetch("https://classes.example.edu/syllabus")
        self.assertEqual(result.media_type, "text/html")
        self.assertIn(b"Course schedule", result.content)

    async def test_blocks_private_network_before_request(self) -> None:
        called = False

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, content=b"should not be called")

        with self.assertRaises(UnsafeUrlError):
            await SafeUrlFetcher(
                resolver=private_resolver,
                transport=httpx.MockTransport(handler),
            ).fetch("https://internal.example.edu/syllabus")
        self.assertFalse(called)

    async def test_rejects_redirects(self) -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                302, headers={"location": "https://example.edu/login"}
            )
        )
        with self.assertRaises(UnsafeUrlError):
            await SafeUrlFetcher(
                resolver=public_resolver,
                transport=transport,
            ).fetch("https://classes.example.edu/syllabus")


class SourceIngestionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_is_hashed_normalized_and_stored_privately(self) -> None:
        store = MemorySnapshotStore()
        service = SourceIngestionService(store=store)
        source = await service.add_upload(
            course_id="cs-101",
            filename="syllabus.md",
            content=b"# Schedule\n\nHomework due Friday",
            media_type="text/markdown",
        )
        self.assertEqual(source.kind, SourceKind.UPLOAD)
        self.assertTrue(source.content_hash)
        self.assertEqual(source.object_ref, f"memory://{source.id}")
        self.assertEqual(store.saved[0][2], "# Schedule\nHomework due Friday")

        repeated = await service.add_upload(
            course_id="cs-101",
            filename="syllabus.md",
            content=b"# Schedule\n\nHomework due Friday",
            media_type="text/markdown",
        )
        self.assertEqual(repeated.id, source.id)


class SourceRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemorySnapshotStore()
        self.service = SourceIngestionService(store=self.store)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_source_service] = lambda: self.service
        self.client = TestClient(app)

    def test_upload_returns_metadata_without_document_content(self) -> None:
        response = self.client.post(
            "/api/sources/upload",
            data={"course_id": "cs-101"},
            files={"file": ("syllabus.txt", b"Exam on September 10", "text/plain")},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["course_id"], "cs-101")
        self.assertNotIn("Exam on September 10", response.text)

    def test_unsupported_upload_returns_reviewable_error(self) -> None:
        response = self.client.post(
            "/api/sources/upload",
            data={"course_id": "cs-101"},
            files={"file": ("syllabus.docx", b"binary", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 422)


class EventExtractorTest(unittest.IsolatedAsyncioTestCase):
    def source(self) -> Source:
        return Source(
            id="source-1",
            course_id="course-1",
            kind=SourceKind.URL,
            label="Syllabus",
            url="https://classes.example.edu/syllabus",
            content_hash="abc",
            fetched_at=datetime.now(UTC),
        )

    async def test_schema_valid_output_becomes_source_linked_candidate(self) -> None:
        model = FakeModel(
            """{"events":[{"kind":"exam","title":"Midterm 1","start_at":"2026-09-24T18:00:00-07:00","end_at":"2026-09-24T20:00:00-07:00","all_day_date":null,"location":"Dwinelle 155","recurrence":[],"evidence":"Midterm 1: Sep 24, 6–8pm, Dwinelle 155","confidence":0.98}]}"""
        )
        candidates = await EventExtractor(model).extract(
            source=self.source(),
            normalized_text="Midterm 1: Sep 24, 6–8pm, Dwinelle 155",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, "source-1")
        self.assertEqual(
            str(candidates[0].source_url), "https://classes.example.edu/syllabus"
        )
        self.assertTrue(candidates[0].eligible_for_auto_import)
        self.assertIn("Course source begins", model.prompts[0])

    async def test_malformed_or_naive_model_output_fails_closed(self) -> None:
        with self.assertRaises(ExtractionError):
            await EventExtractor(FakeModel("not json")).extract(
                source=self.source(),
                normalized_text="Exam September 24",
            )
        naive = """{"events":[{"kind":"exam","title":"Midterm","start_at":"2026-09-24T18:00:00","evidence":"Midterm Sep 24 at 6pm","confidence":0.95}]}"""
        with self.assertRaises(ExtractionError):
            await EventExtractor(FakeModel(naive)).extract(
                source=self.source(),
                normalized_text="Midterm Sep 24 at 6pm",
            )

    async def test_oversized_model_input_is_not_sent(self) -> None:
        model = FakeModel('{"events":[]}')
        with self.assertRaises(ExtractionError):
            await EventExtractor(model).extract(
                source=self.source(),
                normalized_text="x" * (MAX_MODEL_SOURCE_CHARACTERS + 1),
            )
        self.assertEqual(model.prompts, [])

    def test_adk_agent_has_schema_and_no_tools(self) -> None:
        model = AdkGeminiModel()
        self.assertEqual(model.agent.tools, [])
        self.assertIsNotNone(model.agent.output_schema)


if __name__ == "__main__":
    unittest.main()
