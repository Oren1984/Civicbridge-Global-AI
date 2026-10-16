"""Deterministic lexical "hash" embeddings: feature-hashed unigrams, bigrams and 5-char prefixes, L2-normalised.

This is NOT a semantic language model. It needs no download and is fully reproducible, which keeps the core
journeys working offline. Retrieval quality is lexical; the UI and docs label it as such.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.models.jurisdiction import EMBED_DIM

_TOKEN = re.compile(r"[\w֐-׿]+", re.UNICODE)
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "with", "by", "at", "as", "it",
    "this", "that", "what", "how", "do", "i", "my", "me", "can", "der", "die", "das", "und", "ist", "ein", "eine",
    "zu", "mit", "von", "für", "את", "של", "על", "עם", "זה", "מה", "איך", "אני", "או", "גם",
}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


def canon(t: str) -> str:
    """Crude language-agnostic normalisation: drop a plural 's', then keep at most 6 characters
    (so register/registration and document/documents meet). Lexical only, by design."""
    if len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return t[:6]


def canon_tokens(text: str) -> set[str]:
    return {canon(t) for t in tokens(text)}


def _bucket(feature: str) -> tuple[int, float]:
    h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
    return h % EMBED_DIM, (1.0 if (h >> 63) & 1 else -1.0)


def embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    toks = tokens(text)
    feats: list[tuple[str, float]] = []
    for i, t in enumerate(toks):
        feats.append((f"c:{canon(t)}", 1.0))
        feats.append((f"u:{t}", 0.5))
        if i + 1 < len(toks):
            feats.append((f"b:{canon(t)}_{canon(toks[i + 1])}", 0.4))
    for f, w in feats:
        idx, sign = _bucket(f)
        vec[idx] += sign * w
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def chunk_text(text: str, size: int = 700, overlap: int = 100) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text):
        out.append(text[i : i + size])
        i += size - overlap
    return out[:200]
