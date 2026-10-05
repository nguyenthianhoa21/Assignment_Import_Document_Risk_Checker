from __future__ import annotations

import asyncio
import functools
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

# Minimum characters of offline-extracted text before the text-first branch
# is preferred over the vision branch.
MIN_TEXT_CHARS = 50

# Tried in order when the configured model is rejected by the API (404).
FALLBACK_MODELS = ("gemini-2.5-flash",)

BASE_INSTRUCTIONS = """You extract import/export documents.

Set `doc_type` to one of: COMMERCIAL_INVOICE, PACKING_LIST, BILL_OF_LADING, UNKNOWN.

Rules:
- Copy text EXACTLY. Never correct typos, reorder or round numbers.
  e.g. `IV-2026-100B` stays `IV-2026-100B`, `OOLU7654327` stays `OOLU7654327`.
- Missing value -> null. Never invent.
- Put the literal source line for key fields (numbers, weights, dates, ids)
  into `snippets` as evidence.
- Reply with one raw JSON object only. No markdown fences, no commentary.

JSON Schema:
"""

# Gemini free tier allows ~15 RPM; cap concurrency and process documents
# of a shipment sequentially.
_semaphore = asyncio.Semaphore(2)


# --- Schema hint ----------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _schema_hint() -> str:
    """JSON Schema of ExtractedDocument embedded in the prompt.

    Cached so the (deterministic) schema is serialised once per process.
    `title`, `default` and `$defs` are stripped because the Gemini API
    rejects them.
    """
    return json.dumps(
        _clean_schema(ExtractedDocument.model_json_schema()),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _clean_schema(node: Any) -> Any:
    """Recursively drop `title`, `default` and `$defs` from a JSON schema."""
    if isinstance(node, dict):
        return {
            key: _clean_schema(value)
            for key, value in node.items()
            if key not in ("title", "default", "$defs")
        }
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    return node


# --- Response handling -----------------------------------------------------
def _strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    return re.sub(r"\s*```$", "", re.sub(r"^```[a-zA-Z]*\s*", "", stripped)).strip()


def _parse_response(response_text: str) -> ExtractedDocument:
    """Clean, parse and validate the model output."""
    cleaned = _strip_code_fence(response_text)
    try:
        return ExtractedDocument.model_validate_json(cleaned)
    except Exception:
        # Fall back to the outermost JSON object in the response.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        logger.warning("Model added surrounding text; retrying on the JSON object only")
        return ExtractedDocument.model_validate_json(match.group(0))


def _build_prompt(source: str, raw_text: str | None = None) -> str:
    """Assemble instructions + schema + source. Schema is injected once."""
    parts = [BASE_INSTRUCTIONS, _schema_hint(), source]
    if raw_text:
        parts.append(raw_text)
    return "\n".join(parts)


TEXT_SOURCE = "Extract the data. Reply with raw JSON only."
VISION_SOURCE = "Scan this document image. Extract the data. Reply with raw JSON only."


# --- Model handling --------------------------------------------------------
def is_model_not_found(exc: BaseException) -> bool:
    """404 / model-deprecated errors trigger the fallback model."""
    text = str(exc).lower()
    return "404" in text or "not found" in text or "notfound" in text


def is_transient_error(exc: BaseException) -> bool:
    """429 / quota errors are retryable with exponential backoff."""
    text = str(exc)
    return "429" in text or "ResourceExhausted" in type(exc).__name__


def _build_model(name: str) -> genai.GenerativeModel:
    return genai.GenerativeModel(
        name,
        system_instruction=BASE_INSTRUCTIONS,
        generation_config={
            "temperature": settings.ai_temperature,
            "response_mime_type": "application/json",
        },
    )


def _model_candidates() -> list[str]:
    """Configured model first, then any fallbacks (deduplicated)."""
    names = [settings.gemini_model, *FALLBACK_MODELS]
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


@functools.lru_cache(maxsize=1)
def _get_model() -> genai.GenerativeModel:
    """Return a model instance for the first candidate that the API accepts."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    genai.configure(api_key=settings.gemini_api_key)

    candidates = _model_candidates()
    first = candidates[0]
    for name in candidates[1:]:
        logger.info("Model fallback chain: %s -> %s", first, name)
    model = _build_model(first)
    object.__setattr__(model, "_risk_checker_fallbacks", tuple(candidates[1:]))
    return model


def _fallbacks(model: genai.GenerativeModel) -> tuple[str, ...]:
    return tuple(getattr(model, "_risk_checker_fallbacks", ()) or ())


def _next_fallback(
    model: genai.GenerativeModel, error: BaseException
) -> genai.GenerativeModel | None:
    """Swap to the next fallback model if `error` is a 404."""
    if not is_model_not_found(error):
        return None
    remaining = _fallbacks(model)
    if not remaining:
        return None
    nxt = remaining[0]
    logger.warning("Model rejected (%s); retrying with %s", error, nxt)
    replacement = _build_model(nxt)
    object.__setattr__(
        replacement, "_risk_checker_fallbacks", tuple(remaining[1:])
    )
    return replacement


def _request(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> tuple[str, genai.GenerativeModel]:
    """Blocking call with 404 fallback. Returns (raw text, model used)."""
    current = model
    while True:
        try:
            if inline and mime:
                response = current.generate_content(
                    [{"mime_type": mime, "data": inline}, prompt]
                )
            else:
                response = current.generate_content(prompt)
            return response.text, current
        except Exception as exc:  # noqa: BLE001
            replacement = _next_fallback(current, exc)
            if replacement is None:
                raise
            current = replacement


async def _request_async(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> tuple[str, genai.GenerativeModel]:
    """Async call, throttled by the shared semaphore, with 404 fallback."""
    current = model
    while True:
        try:
            async with _semaphore:
                if inline and mime:
                    response = await current.generate_content_async(
                        [{"mime_type": mime, "data": inline}, prompt]
                    )
                else:
                    response = await current.generate_content_async(prompt)
            return response.text, current
        except Exception as exc:  # noqa: BLE001
            replacement = _next_fallback(current, exc)
            if replacement is None:
                raise
            current = replacement


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
    raw, _ = await _request_async(model, prompt, inline, mime)
    return _parse_response(raw)


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
    raw, _ = _request(model, prompt, inline, mime)
    return _parse_response(raw)


# --- Public API ------------------------------------------------------------
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
