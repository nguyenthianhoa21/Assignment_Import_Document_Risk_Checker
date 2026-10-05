from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path

import google.generativeai as genai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.extraction import ExtractedDocument

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an import/export document extraction engine.

Classify the document into exactly one of:
COMMERCIAL_INVOICE, PACKING_LIST, BILL_OF_LADING, UNKNOWN.

Extract structured data following the provided JSON schema.

STRICT VERBATIM EXTRACTION RULES:
- Preserve every character exactly as printed. Never correct typos, never
  normalise numbers, never round values, never translate.
- If the invoice number reads IV-2026-100B, output IV-2026-100B.
- If a container number reads OOLU7654327, output OOLU7654327.
- Copy weights, amounts, dates and names character-for-character.
- For every important field, also copy the exact source sentence into the
  `snippets` object so the UI can highlight the evidence.
- If a field is absent, return null. Do not invent values.
"""

_semaphore = asyncio.Semaphore(2)


def is_transient_error(exc: BaseException) -> bool:
    text = str(exc)
    return "429" in text or "ResourceExhausted" in type(exc).__name__


def _get_model() -> genai.GenerativeModel:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        settings.gemini_model,
        system_instruction=SYSTEM_PROMPT,
        generation_config={
            "temperature": settings.ai_temperature,
            "response_mime_type": "application/json",
            "response_schema": ExtractedDocument,
        },
    )


@retry(
    retry=retry_if_exception(is_transient_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def _generate(model: genai.GenerativeModel, prompt: str, inline: bytes | None, mime: str | None) -> ExtractedDocument:
    async with _semaphore:
        if inline and mime:
            response = await model.generate_content_async(
                [{"mime_type": mime, "data": inline}, prompt]
            )
        else:
            response = await model.generate_content_async(prompt)
        payload = json.loads(response.text)
        return ExtractedDocument.model_validate(payload)


def _generate_sync(model: genai.GenerativeModel, prompt: str, inline: bytes | None, mime: str | None) -> ExtractedDocument:
    if inline and mime:
        response = model.generate_content([{"mime_type": mime, "data": inline}, prompt])
    else:
        response = model.generate_content(prompt)
    payload = json.loads(response.text)
    return ExtractedDocument.model_validate(payload)


@retry(
    retry=retry_if_exception(is_transient_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _generate_sync_retry(model: genai.GenerativeModel, prompt: str, inline: bytes | None, mime: str | None) -> ExtractedDocument:
    return _generate_sync(model, prompt, inline, mime)


async def extract_document(file_path: str, raw_text: str) -> ExtractedDocument:
    model = _get_model()
    path = Path(file_path)
    if raw_text and len(raw_text.strip()) > 50:
        prompt = "Extract the structured data from the following document text. Return JSON only.\n\nDOCUMENT TEXT:\n" + raw_text
        return await _generate(model, prompt, None, None)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    inline = path.read_bytes()
    prompt = "This is a scanned/image document. Read it with vision and extract the structured data. Return JSON only."
    return await _generate(model, prompt, inline, mime)


def extract_document_sync(file_path: str, raw_text: str) -> ExtractedDocument:
    """Synchronous variant used by the background worker thread."""
    model = _get_model()
    path = Path(file_path)
    if raw_text and len(raw_text.strip()) > 50:
        prompt = "Extract the structured data from the following document text. Return JSON only.\n\nDOCUMENT TEXT:\n" + raw_text
        return _generate_sync_retry(model, prompt, None, None)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    inline = path.read_bytes()
    prompt = "This is a scanned/image document. Read it with vision and extract the structured data. Return JSON only."
    return _generate_sync_retry(model, prompt, inline, mime)
