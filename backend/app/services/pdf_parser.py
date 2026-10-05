from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pdfplumber


def extract_text(path: str) -> str:
    """Return the text of a PDF, or an empty string for scans/images."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"}:
        # Images carry no extractable text; the vision branch handles them.
        return ""
    try:
        with pdfplumber.open(BytesIO(p.read_bytes())) as pdf:
            parts: list[str] = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                parts.append(text)
            return "\n".join(parts).strip()
    except Exception:
        return ""


def is_scanned(text: str, min_chars: int = 50) -> bool:
    return len(text.strip()) < min_chars
