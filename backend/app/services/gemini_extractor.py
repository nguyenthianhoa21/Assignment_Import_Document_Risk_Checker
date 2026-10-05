from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.extraction import ExtractedDocument

logger = logging.getLogger(__name__)

# Minimum characters of offline-extracted text before we prefer the
# text-first branch over the vision branch.
MIN_TEXT_CHARS = 50

BASE_INSTRUCTIONS = """You are an import/export document extraction engine.

Classify the document into exactly one of:
COMMERCIAL_INVOICE, PACKING_LIST, BILL_OF_LADING, UNKNOWN.

STRICT VERBATIM EXTRACTION RULES:
- Preserve every character exactly as printed. Never correct typos, never
  normalise numbers, never round values, never translate.
- If the invoice number reads IV-2026-100B, output IV-2026-100B.
- If a container number reads OOLU7654327, output OOLU7654327.
- Copy weights, amounts, dates and names character-for-character.
- For every important field, also copy the exact source sentence into the
  `snippets` object so the UI can highlight the evidence.
- If a field is absent, return null. Do not invent values.

RESPONSE FORMAT:
- Respond with a single raw JSON object and nothing else.
- Do not wrap it in markdown code fences and do not add commentary.
- The JSON object must follow this JSON Schema exactly:

"""

# Rate-limit guard: Gemini free tier allows ~15 RPM, so cap concurrency and
# process a shipment's documents one at a time.
_semaphore = asyncio.Semaphore(2)


def _schema_hint() -> str:
    """JSON Schema of ExtractedDocument, with non-essential keys removed.

    Pydantic emits `title`, `default` and `$defs` which the Gemini API rejects,
    so they are stripped before the schema is embedded in the prompt.
    """
    raw = ExtractedDocument.model_json_schema()
    return json.dumps(_clean_schema(raw), ensure_ascii=False, indent=2)


def _clean_schema(node: Any) -> Any:
    """Recursively drop `title`, `default` and `$defs` from a JSON schema."""
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("title", "default", "$defs"):
                continue
            cleaned[key] = _clean_schema(value)
        return cleaned
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    return node


def _strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _parse_response(response_text: str) -> ExtractedDocument:
    """Clean, parse and validate the model output."""
    cleaned = _strip_code_fence(response_text)
    try:
        return ExtractedDocument.model_validate_json(cleaned)
    except Exception:
        # Fall back to locating the outermost JSON object in the response.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        logger.warning("Retrying validation after trimming surrounding text")
        return ExtractedDocument.model_validate_json(match.group(0))


def _build_prompt(source: str, raw_text: str | None = None) -> str:
    parts = [BASE_INSTRUCTIONS, _schema_hint(), "", source]
    if raw_text:
        parts += ["", "DOCUMENT TEXT:", raw_text]
    return "\n".join(parts)


TEXT_SOURCE = (
    "Extract the structured data from the following document text. "
    "Respond with raw JSON only."
)
VISION_SOURCE = (
    "This is a scanned document or image. Read it with vision and extract the "
    "structured data. Respond with raw JSON only."
)


def is_transient_error(exc: BaseException) -> bool:
    """429 / quota errors are retryable with exponential backoff."""
    text = str(exc)
    return "429" in text or "ResourceExhausted" in type(exc).__name__


def _get_model() -> genai.GenerativeModel:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        settings.gemini_model,
        system_instruction=BASE_INSTRUCTIONS,
        generation_config={
            "temperature": settings.ai_temperature,
            "response_mime_type": "application/json",
        },
    )


def _request(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> str:
    """Run one blocking Gemini call and return the raw text."""
    if inline and mime:
        response = model.generate_content([{"mime_type": mime, "data": inline}, prompt])
    else:
        response = model.generate_content(prompt)
    return response.text


async def _request_async(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> str:
    """Run one Gemini call, throttled by the shared semaphore."""
    async with _semaphore:
        if inline and mime:
            response = await model.generate_content_async(
                [{"mime_type": mime, "data": inline}, prompt]
            )
        else:
            response = await model.generate_content_async(prompt)
        return response.text


@retry(
    retry=retry_if_exception(is_transient_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def _generate(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> ExtractedDocument:
    return _parse_response(await _request_async(model, prompt, inline, mime))


@retry(
    retry=retry_if_exception(is_transient_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _generate_sync(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> ExtractedDocument:
    return _parse_response(_request(model, prompt, inline, mime))


async def extract_document(file_path: str, raw_text: str) -> ExtractedDocument:
    """Hybrid extraction: offline text first, vision fallback for scans."""
    model = _get_model()
    path = Path(file_path)

    if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS:
        return await _generate(model, _build_prompt(TEXT_SOURCE, raw_text), None, None)

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return await _generate(
        model, _build_prompt(VISION_SOURCE), path.read_bytes(), mime
    )


def extract_document_sync(file_path: str, raw_text: str) -> ExtractedDocument:
    """Synchronous variant used by the background worker thread."""
    model = _get_model()
    path = Path(file_path)

    if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS:
        return _generate_sync(model, _build_prompt(TEXT_SOURCE, raw_text), None, None)

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return _generate_sync(model, _build_prompt(VISION_SOURCE), path.read_bytes(), mime)
