"""Embedding backends. Vectors are L2-normalized so cosine is a dot product."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from server.config import settings

TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Dependency-free embedder: hashed unigrams and bigrams, signed buckets.

    Identical text gives similarity 1.0, small edits stay high, and new claims
    pull similarity down. Good enough for tests and the offline demo.
    """

    dim = 384

    def embed(self, text: str) -> list[float]:
        tokens = TOKEN_RE.findall(text.lower())
        features = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
        vec = [0.0] * self.dim
        for feat in features:
            h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            bucket = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[bucket] += sign
        return _normalize(vec)


class SentenceTransformerEmbedder:
    dim = 384

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model)

    def embed(self, text: str) -> list[float]:
        return _normalize([float(x) for x in self._model.encode(text)])


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.embedder == "sentence-transformers":
        return SentenceTransformerEmbedder()
    return HashingEmbedder()
