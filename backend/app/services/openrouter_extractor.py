from __future__ import annotations

"""AI extraction via the OpenRouter API (open-weights models, free tier).

Primary model: ``nvidia/nemotron-3.5-lightning:free``.

The flow is:

1. Try the OpenRouter ``/chat/completions`` endpoint with the configured
   model, then the fallback models. Any transport failure, non-200 status,
   empty content, or Pydantic validation failure moves to the next model
   (this includes HTTP 429 rate limits).
2. When every model fails, fall back to the offline deterministic parser so
   the pipeline never goes dark (an empty document set would validate to a
   false PASSED verdict).
"""

import asyncio
import functools
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.schemas.extraction import DocumentType, ExtractedDocument
from app.services import extraction_offline

logger = logging.getLogger(__name__)

# Minimum characters of offline-extracted text before the text-first branch
# is preferred over the vision branch.
MIN_TEXT_CHARS = 50

SYSTEM_PROMPT = (
    "You are a logistics document extractor. Extract structured data from the text "
    "and return ONLY a valid JSON object matching the ExtractedDocument schema. "
    "Do not output markdown code blocks or explanations.\n"
    "Copy every identifier VERBATIM: invoice numbers (e.g. IV-2026-100B stays "
    "IV-2026-100B), container numbers (e.g. OOLU7654327 stays OOLU7654327), "
    "seals, weights, dates. Never fix typos, never round or reformat numbers.\n"
    "A missing value is null. Never invent data."
)

TEXT_USER_PROMPT = "Extract the document below. Reply with raw JSON only."
VISION_USER_PROMPT = (
    "This is a scanned document image with no extractable text. "
    "Describe it as an UNKNOWN document with null fields. Reply with raw JSON only."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

# Uploaded images are sent to vision-capable models only when the free Qwen
# model cannot accept them; pdfplumber text is the primary source.
_semaphore = asyncio.Semaphore(2)


# --- Response handling -----------------------------------------------------
def _strip_think_tags(text: str) -> str:
    """Remove ``<think>...</think>`` reasoning blocks some models emit."""
    return _THINK_RE.sub("", text)


def _strip_code_fence(text: str) -> str:
    """Remove surrounding ```json ... ``` fences if the model added them."""
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    return _FENCE_RE.sub("", stripped).strip()


def clean_model_text(text: str) -> str:
    """Normalise raw model output into a bare JSON string."""
    return _strip_code_fence(_strip_think_tags(text or "")).strip()


def _clean_schema(node: Any) -> Any:
    """Drop keys OpenRouter/free models choke on when echoed back."""
    if isinstance(node, dict):
        return {
            key: _clean_schema(value)
            for key, value in node.items()
            if key not in ("title", "default", "$defs")
        }
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    return node


@functools.lru_cache(maxsize=1)
def _schema_hint() -> str:
    return json.dumps(
        _clean_schema(ExtractedDocument.model_json_schema()),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalise_doc_type(value: Any) -> Any:
    """Accept loose doc_type spellings such as ``"COMMERCIAL INVOICE"``.

    Free models frequently return the enum value with spaces or hyphens, which
    Pydantic rejects. Normalising here keeps a correct extraction from being
    thrown away over a formatting detail.
    """
    if not isinstance(value, str):
        return value
    candidate = re.sub(r"[\s\-]+", "_", value.strip().upper())
    for doc_type in DocumentType:
        if candidate == doc_type.value:
            return doc_type.value
    aliases = {
        "INVOICE": DocumentType.COMMERCIAL_INVOICE.value,
        "COMMERCIAL_INVOICE": DocumentType.COMMERCIAL_INVOICE.value,
        "PACKING_LIST": DocumentType.PACKING_LIST.value,
        "PACKINGLIST": DocumentType.PACKING_LIST.value,
        "BILL_OF_LADING": DocumentType.BILL_OF_LADING.value,
        "BILL_OF_LADING": DocumentType.BILL_OF_LADING.value,
        "B/L": DocumentType.BILL_OF_LADING.value,
        "BILL_OF_LADE": DocumentType.BILL_OF_LADING.value,
    }
    return aliases.get(candidate, value)


def _coerce(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise loosely typed fields before validation."""
    if "doc_type" in payload:
        payload["doc_type"] = _normalise_doc_type(payload["doc_type"])
    return payload


def _parse_response(content: str) -> ExtractedDocument:
    """Clean, parse and validate the model output."""
    cleaned = clean_model_text(content)
    try:
        return ExtractedDocument.model_validate_json(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        logger.warning("Model added surrounding text; retrying on the JSON object only")
        payload = json.loads(match.group(0))
        return ExtractedDocument.model_validate(_coerce(payload))


# --- OpenRouter client -----------------------------------------------------
def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key or ''}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_http_referer,
        "X-Title": settings.openrouter_app_title,
    }


def _payload(model: str, raw_text: str | None) -> dict[str, Any]:
    """Request body for ``POST /chat/completions``.

    The user message embeds the PDF text and the full ``ExtractedDocument``
    JSON schema so the model returns a directly validatable object.
    ``response_format`` is best-effort: some free models ignore it, so the
    response parser strips fences and reasoning tokens anyway.
    """
    schema = json.dumps(
        _clean_schema(ExtractedDocument.model_json_schema()),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_content = (
        f"Document text:\n{raw_text}\n\nSchema:\n{schema}"
        if raw_text
        else f"Document text: (empty)\n\nSchema:\n{schema}"
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        # Bound the completion: some free reasoning models loop indefinitely on
        # a large schema and never emit JSON. Capping turns an unbounded wait
        # into a fast, clean failover to the next model.
        "max_tokens": settings.openrouter_max_tokens,
    }


def _extract_content(response: httpx.Response) -> str:
    data = response.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected OpenRouter payload: {str(data)[:300]}") from exc


def _call_model_sync(model: str, raw_text: str | None) -> ExtractedDocument:
    with httpx.Client(timeout=settings.openrouter_timeout_seconds) as client:
        response = client.post(
            settings.openrouter_base_url, headers=_headers(), json=_payload(model, raw_text)
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter HTTP {response.status_code}: {response.text[:300]}"
        )
    return _parse_response(_extract_content(response))


async def _call_model_async(model: str, raw_text: str | None) -> ExtractedDocument:
    async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
        async with _semaphore:
            response = await client.post(
                settings.openrouter_base_url,
                headers=_headers(),
                json=_payload(model, raw_text),
            )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter HTTP {response.status_code}: {response.text[:300]}"
        )
    return _parse_response(_extract_content(response))


def _fallback_models() -> list[str]:
    return settings.openrouter_models


def _offline_or_raise(file_path: str, raw_text: str, exc: Exception) -> ExtractedDocument:
    """Last-resort deterministic extraction: the pipeline must never go dark."""
    if settings.offline_fallback_enabled and raw_text and raw_text.strip():
        logger.warning(
            "OpenRouter extraction failed (%s: %s); using offline deterministic parser.",
            type(exc).__name__,
            str(exc)[:200],
        )
        return extraction_offline.extract_document_offline(raw_text, file_path)
    raise exc


# --- Public API ------------------------------------------------------------
def extract_document_sync(file_path: str, raw_text: str) -> ExtractedDocument:
    """Synchronous extraction used by the background worker thread."""
    if not settings.openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY is not configured; using offline parser.")
        return extraction_offline.extract_document_offline(raw_text, file_path)

    path = Path(file_path)
    text = raw_text if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS else None
    if text is None and path.suffix.lower() not in {".pdf"}:
        logger.info("Image upload %s has no extractable text; using offline parser.", path.name)
        return extraction_offline.extract_document_offline(raw_text, file_path)

    last_error: Exception | None = None
    for model in _fallback_models():
        try:
            logger.info("Extracting %s with OpenRouter model %s", path.name, model)
            return _call_model_sync(model, text)
        except Exception as exc:  # noqa: BLE001
            last_error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
            logger.warning("Model %s failed (%s); trying next.", model, str(exc)[:200])
            continue
    return _offline_or_raise(
        file_path, raw_text, last_error or RuntimeError("OpenRouter extraction failed")
    )


async def extract_document(file_path: str, raw_text: str) -> ExtractedDocument:
    """Async extraction used by request-scoped code paths."""
    if not settings.openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY is not configured; using offline parser.")
        return extraction_offline.extract_document_offline(raw_text, file_path)

    path = Path(file_path)
    text = raw_text if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS else None
    if text is None and path.suffix.lower() not in {".pdf"}:
        return extraction_offline.extract_document_offline(raw_text, file_path)

    last_error: Exception | None = None
    for model in _fallback_models():
        try:
            logger.info("Extracting %s with OpenRouter model %s", path.name, model)
            return await _call_model_async(model, text)
        except Exception as exc:  # noqa: BLE001
            last_error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
            logger.warning("Model %s failed (%s); trying next.", model, str(exc)[:200])
            continue
    return _offline_or_raise(
        file_path, raw_text, last_error or RuntimeError("OpenRouter extraction failed")
    )
