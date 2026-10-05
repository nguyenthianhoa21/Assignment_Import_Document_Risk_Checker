from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Z0-9]+")

def _tokens(text: str) -> list[str]:
    return [m.group(0) for m in _WORD_RE.finditer((text or "").upper())]

def _diff_tokens(text1: str, text2: str) -> list[str]:
    a = set(_tokens(text1))
    b = set(_tokens(text2))
    return sorted((a ^ b), key=lambda s: (len(s), s))

def _strict_from_tokens(text1: str, text2: str) -> tuple[bool, float, list[str]]:
    if (text1 or "").strip() == (text2 or "").strip():
        return True, 1.0, []
    diff = _diff_tokens(text1, text2)
    score = 1.0 if not diff else 0.0
    return (False, score, diff) if diff else (True, 1.0, [])

@dataclass(frozen=True)
class BGECompareResult:
    is_consistent: bool
    score: float
    diff_tokens: list[str]

class BGEMatcher:
    _lock = threading.Lock()
    _model = None
    _unavailable_reason: str | None = None

    @classmethod
    def _model_name(cls) -> str:
        from app.config import settings
        return (settings.bge_model_name or "BAAI/bge-m3").strip()

    @classmethod
    def _threshold(cls) -> float:
        from app.config import settings
        try:
            return float(settings.bge_similarity_threshold)
        except (TypeError, ValueError):
            return 0.995

    STRICT_THRESHOLD = 0.995  # default; live value comes from settings.bge_similarity_threshold

    @classmethod
    def _ensure_model(cls):
        if cls._model is not None or cls._unavailable_reason is not None:
            return
        try:
            from app.config import settings as _s
            if not getattr(_s, "bge_model_enabled", True):
                cls._unavailable_reason = "disabled by BGE_MODEL_ENABLED=false"
                return
        except Exception:
            pass
        with cls._lock:
            if cls._model is not None or cls._unavailable_reason is not None:
                return
            try:
                import torch  # noqa: F401
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                cls._unavailable_reason = f"deps missing: {exc}"
                logger.warning("BGE-M3 model unavailable (%s); using deterministic fallback.", exc)
                return
            device = "cuda" if hasattr(__import__("torch"), "cuda") and __import__("torch").cuda.is_available() else "cpu"
            try:
                m = SentenceTransformer(cls._model_name(), device=device)
                m.encode(["ok"], convert_to_tensor=False, normalize_embeddings=True)
                cls._model = m
                cls._unavailable_reason = None
                logger.info("BGE-M3 loaded on %s.", device)
            except Exception as exc:
                cls._unavailable_reason = str(exc)
                cls._model = None
                logger.warning("BGE-M3 load failed (%s); using deterministic fallback.", exc)

    @classmethod
    def compare(cls, text1: str | None, text2: str | None) -> BGECompareResult:
        t1 = (text1 or "").strip()
        t2 = (text2 or "").strip()
        if t1 == t2:
            return BGECompareResult(True, 1.0, [])
        try:
            diff = _diff_tokens(t1, t2)
        except Exception:
            diff = []
        cls._ensure_model()
        if cls._model is None:
            ok, score, diff2 = _strict_from_tokens(t1, t2)
            return BGECompareResult(ok, score, diff2)
        try:
            embs = cls._model.encode(
                [t1, t2], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
            )
            a = embs[0].astype("float64")
            b = embs[1].astype("float64")
            n = float((a @ a) ** 0.5) * float((b @ b) ** 0.5)
            cos = float((a @ b) / n) if n else 0.0
            if cos > 1.0:
                cos = 1.0
            elif cos < -1.0:
                cos = -1.0
        except Exception as exc:
            logger.warning("BGE-M3 encode failed (%s); using deterministic fallback.", exc)
            ok, score, diff2 = _strict_from_tokens(t1, t2)
            return BGECompareResult(ok, score, diff2)
        is_consistent = (len(diff) == 0) and (cos >= cls._threshold())
        return BGECompareResult(is_consistent, cos, diff)

    @classmethod
    def status(cls) -> str:
        if cls._model is not None:
            return f"ready:{cls._model_name()}"
        if cls._unavailable_reason:
            return f"fallback:{cls._unavailable_reason[:120]}"
        return "lazy: not yet loaded"
