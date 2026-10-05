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

from app.config import ACTIVE_GEMINI_MODELS, settings
from app.schemas.extraction import ExtractedDocument
from app.services import extraction_offline, key_manager

logger = logging.getLogger(__name__)

# Minimum characters of offline-extracted text before the text-first branch
# is preferred over the vision branch.
MIN_TEXT_CHARS = 50

# Tried in order when the configured model is rejected by the API (404).
# "Live" models only expose the bidirectional WebSocket API and are rejected
# by generate_content, so they always sort last (probe target only).
CANDIDATE_MODELS = [m for m in ACTIVE_GEMINI_MODELS if "live" not in m.lower()] + [
    m for m in ACTIVE_GEMINI_MODELS if "live" in m.lower()
]

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


class _NoHealthyKey(RuntimeError):
    """Every key in the pool is in cooldown; go offline immediately."""


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
    """429 / quota errors are retried with backoff — unless keys are exhausted."""
    if isinstance(exc, _NoHealthyKey):
        return False
    text = str(exc)
    return "429" in text or "ResourceExhausted" in type(exc).__name__


def is_live_model_error(exc: BaseException) -> bool:
    """Live-only models reject generate_content; treat like a 404."""
    text = str(exc).lower()
    return "bidigeneratecontent" in text or "websocket" in text or "realtime" in text


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
    names = [settings.gemini_model, *CANDIDATE_MODELS]
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


@functools.lru_cache(maxsize=1)
def _get_model() -> genai.GenerativeModel:
    """Return a model instance, configured with the active pool key.

    The key lives in the global ``genai`` configuration, so rotating the pool
    key does not invalidate this cached instance.
    """
    pool = key_manager.get_pool()
    active = pool.configure()
    logger.info("Using Gemini key ...%s with model %s", active[-4:], settings.gemini_model)

    candidates = _model_candidates()
    first = candidates[0]
    for name in candidates[1:]:
        logger.info("Model fallback chain: %s -> %s", first, name)
    model = _build_model(first)
    object.__setattr__(model, "_risk_checker_fallbacks", tuple(candidates[1:]))
    return model


def reset_model_cache() -> None:
    """Drop the cached model (used after config changes and in tests)."""
    _get_model.cache_clear()


def _fallbacks(model: genai.GenerativeModel) -> tuple[str, ...]:
    return tuple(getattr(model, "_risk_checker_fallbacks", ()) or ())


def _next_fallback(
    model: genai.GenerativeModel, error: BaseException
) -> genai.GenerativeModel | None:
    """Swap to the next fallback model on 404 / live-model errors."""
    if not (is_model_not_found(error) or is_live_model_error(error)):
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


def _rotate_key_or_raise(exc: BaseException, attempts: int) -> None:
    """Rotate to the next pool key, or fail fast when all keys are down."""
    pool = key_manager.get_pool()
    if not key_manager.is_recoverable_with_next_key(exc):
        raise exc
    if attempts >= max(pool.size, 1):
        raise _NoHealthyKey(
            f"All {pool.size} Gemini key(s) are rate-limited or invalid; "
            "switching to the offline deterministic parser."
        ) from exc
    pool.rotate(exc)
    pool.configure()
    logger.warning(
        "Retrying Gemini request with next key (rotation %d/%d)",
        attempts + 1, pool.size,
    )


def _request(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> tuple[str, genai.GenerativeModel]:
    """Blocking call with model fallback + key rotation.

    Returns (raw text, model used). Raises ``_NoHealthyKey`` when the whole
    pool is exhausted so callers can switch to the offline parser at once.
    """
    current = model
    key_attempts = 0
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
            if replacement is not None:
                current = replacement
                continue
            try:
                _rotate_key_or_raise(exc, key_attempts)
            except _NoHealthyKey:
                raise
            except Exception:
                raise
            key_attempts += 1


async def _request_async(
    model: genai.GenerativeModel,
    prompt: str,
    inline: bytes | None,
    mime: str | None,
) -> tuple[str, genai.GenerativeModel]:
    """Async call, throttled by the shared semaphore, with fallback+rotation."""
    current = model
    key_attempts = 0
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
            if replacement is not None:
                current = replacement
                continue
            try:
                _rotate_key_or_raise(exc, key_attempts)
            except _NoHealthyKey:
                raise
            except Exception:
                raise
            key_attempts += 1


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


def _offline_or_raise(file_path: str, raw_text: str, exc: Exception) -> ExtractedDocument:
    """Last-resort deterministic extraction: the pipeline must never go dark."""
    if settings.offline_fallback_enabled and raw_text and raw_text.strip():
        logger.warning(
            "Gemini extraction failed (%s: %s); using offline deterministic parser.",
            type(exc).__name__, str(exc)[:200],
        )
        return extraction_offline.extract_document_offline(raw_text, file_path)
    raise exc


# --- Public API ------------------------------------------------------------
async def extract_document(file_path: str, raw_text: str) -> ExtractedDocument:
    """Hybrid extraction: offline text first, vision fallback for scans."""
    try:
        model = _get_model()
        path = Path(file_path)

        if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS:
            return await _generate(model, _build_prompt(TEXT_SOURCE, raw_text), None, None)

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return await _generate(
            model, _build_prompt(VISION_SOURCE), path.read_bytes(), mime
        )
    except Exception as exc:  # noqa: BLE001
        return _offline_or_raise(file_path, raw_text, exc)


def extract_document_sync(file_path: str, raw_text: str) -> ExtractedDocument:
    """Synchronous variant used by the background worker thread."""
    try:
        model = _get_model()
        path = Path(file_path)

        if raw_text and len(raw_text.strip()) >= MIN_TEXT_CHARS:
            return _generate_sync(model, _build_prompt(TEXT_SOURCE, raw_text), None, None)

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return _generate_sync(model, _build_prompt(VISION_SOURCE), path.read_bytes(), mime)
    except Exception as exc:  # noqa: BLE001
        return _offline_or_raise(file_path, raw_text, exc)
