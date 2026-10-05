"""Tests for the OpenRouter extraction layer.

Network calls are mocked so the suite runs offline. The offline fallback is
asserted for every failure mode (timeout, non-200, malformed JSON) because an
empty document set would validate to a false PASSED verdict.
"""

from __future__ import annotations

import pathlib
import sys

import httpx
import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.schemas.extraction import DocumentType  # noqa: E402
from app.services import openrouter_extractor  # noqa: E402
from app.services.pdf_parser import extract_text  # noqa: E402

SAMPLE_DIR = BACKEND_ROOT.parent / "Sample"
INVOICE_PDF = SAMPLE_DIR / "Sample_Commercial_Invoice.pdf"

VALID_PAYLOAD = {
    "doc_type": "COMMERCIAL_INVOICE",
    "doc_number": "IV-2026-1008",
    "reference_numbers": [],
    "total_gross_weight_kg": 231000.0,
    "total_net_weight_kg": 220000.0,
    "containers": [],
    "snippets": {},
}


def _response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.fixture(autouse=True)
def _single_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the fallback chain so one failure does not fan out."""
    monkeypatch.setattr(settings, "openrouter_model", "qwen/qwen3.8-27b:free")
    monkeypatch.setattr(
        openrouter_extractor.settings, "openrouter_model", "qwen/qwen3.8-27b:free"
    )
    # Dummy key so the mocked AI branch runs without shipping a real secret.
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        openrouter_extractor.settings, "openrouter_api_key", "test-key", raising=False
    )


# --- Response cleaning ----------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '<think>reasoning here</think>\n```json\n{"doc_type":"UNKNOWN"}\n```',
            '{"doc_type":"UNKNOWN"}',
        ),
        ('```json\n{"doc_type":"COMMERCIAL_INVOICE"}\n```', '{"doc_type":"COMMERCIAL_INVOICE"}'),
        ('{"doc_type":"PACKING_LIST"}', '{"doc_type":"PACKING_LIST"}'),
    ],
)
def test_clean_model_text(raw: str, expected: str) -> None:
    """<think> blocks and markdown fences must be stripped before parsing."""
    assert openrouter_extractor.clean_model_text(raw).strip() == expected


def test_parse_response_handles_think_and_fence() -> None:
    payload = (
        "<think>I should read the invoice number carefully.</think>\n"
        "```json\n"
        '{"doc_type":"COMMERCIAL_INVOICE","doc_number":"IV-2026-1008"}\n'
        "```"
    )
    doc = openrouter_extractor._parse_response(payload)
    assert doc.doc_type is DocumentType.COMMERCIAL_INVOICE
    assert doc.doc_number == "IV-2026-1008"


# --- Request shape --------------------------------------------------------
def test_request_payload_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            import json as _json

            return _response(_json.dumps(VALID_PAYLOAD))

    monkeypatch.setattr(openrouter_extractor.httpx, "Client", _FakeClient)
    doc = openrouter_extractor.extract_document_sync(str(INVOICE_PDF), "IV-2026-1008 text")

    assert doc.doc_number == "IV-2026-1008"
    assert captured["url"] == settings.openrouter_base_url

    headers = captured["headers"]
    assert headers["Authorization"] == f"Bearer {settings.openrouter_api_key}"
    assert headers["Content-Type"] == "application/json"
    assert headers["HTTP-Referer"] == settings.openrouter_http_referer
    assert headers["X-Title"] == settings.openrouter_app_title

    body = captured["json"]
    assert body["model"] == "qwen/qwen3.8-27b:free"
    assert body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "logistics" in body["messages"][0]["content"].lower()


# --- Failover to the offline parser --------------------------------------
def test_non_200_falls_back_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FailClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return _response("upstream error", status_code=429)

    monkeypatch.setattr(openrouter_extractor.httpx, "Client", _FailClient)
    raw_text = extract_text(str(INVOICE_PDF))
    doc = openrouter_extractor.extract_document_sync(str(INVOICE_PDF), raw_text)

    assert doc.doc_type is DocumentType.COMMERCIAL_INVOICE
    assert doc.doc_number == "IV-2026-1008"
    assert doc.total_gross_weight_kg == 231000.0


def test_timeout_falls_back_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_TimeoutClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(openrouter_extractor.httpx, "Client", _TimeoutClient)
    raw_text = extract_text(str(INVOICE_PDF))
    doc = openrouter_extractor.extract_document_sync(str(INVOICE_PDF), raw_text)
    assert doc.doc_number == "IV-2026-1008"


def test_malformed_json_falls_back_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    class _GarbageClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_GarbageClient":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return _response("I cannot help with that.")

    monkeypatch.setattr(openrouter_extractor.httpx, "Client", _GarbageClient)
    raw_text = extract_text(str(INVOICE_PDF))
    doc = openrouter_extractor.extract_document_sync(str(INVOICE_PDF), raw_text)
    assert doc.total_gross_weight_kg == 231000.0


def test_missing_api_key_uses_offline_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    raw_text = extract_text(str(INVOICE_PDF))
    doc = openrouter_extractor.extract_document_sync(str(INVOICE_PDF), raw_text)
    assert doc.doc_number == "IV-2026-1008"


# --- Transport ------------------------------------------------------------
@pytest.mark.anyio
async def test_async_extraction_parses_model_json() -> None:
    import json as _json

    class _FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return _response(_json.dumps(VALID_PAYLOAD))

    original = openrouter_extractor.httpx.AsyncClient
    openrouter_extractor.httpx.AsyncClient = _FakeAsyncClient  # type: ignore[assignment]
    try:
        raw_text = extract_text(str(INVOICE_PDF))
        doc = await openrouter_extractor.extract_document(str(INVOICE_PDF), raw_text)
    finally:
        openrouter_extractor.httpx.AsyncClient = original  # type: ignore[assignment]

    assert doc.doc_number == "IV-2026-1008"
    assert doc.total_gross_weight_kg == 231000.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
