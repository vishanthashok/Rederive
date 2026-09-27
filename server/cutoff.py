"""Semantic early cutoff: decide whether a rebuilt record says the same thing.

Similarity is measured per claim, not per document. Each sentence on one
side is matched to its most similar sentence on the other side, and the
score is the weakest match. Whole-text cosine hides small edits in long
records: swapping "Globex" for "Initech" in a 10-sentence profile still
scores above 0.97, and so does dropping 1 of 16 facts. A per-claim score
drops sharply for both.

Order of checks:
  1. identical text                          -> equal
  2. claim similarity below different_below  -> different
  3. claim similarity at or above equal_at   -> equal
  4. otherwise ask the judge model whether any claim differs
"""

from dataclasses import dataclass

from server.config import settings
from server.embed import Embedder, cosine
from server.llm import LLMProvider, normalize, split_sentences


@dataclass(frozen=True)
class CutoffDecision:
    equal: bool
    similarity: float
    method: str  # exact | embedding_equal | embedding_different | judge


def claim_similarity(old_text: str, new_text: str, embedder: Embedder) -> float:
    old = _unique(split_sentences(old_text))
    new = _unique(split_sentences(new_text))
    if not old or not new:
        return 1.0 if old == new else 0.0
    ov = [embedder.embed(s) for s in old]
    nv = [embedder.embed(s) for s in new]
    forward = min(max(cosine(a, b) for b in nv) for a in ov)
    backward = min(max(cosine(b, a) for a in ov) for b in nv)
    return min(forward, backward)


def decide(
    old_text: str,
    new_text: str,
    embedder: Embedder,
    llm: LLMProvider,
    equal_at: float | None = None,
    different_below: float | None = None,
) -> CutoffDecision:
    equal_at = settings.cutoff_equal if equal_at is None else equal_at
    different_below = settings.cutoff_different if different_below is None else different_below

    if old_text.strip() == new_text.strip():
        return CutoffDecision(True, 1.0, "exact")
    sim = claim_similarity(old_text, new_text, embedder)
    if sim < different_below:
        return CutoffDecision(False, sim, "embedding_different")
    if sim >= equal_at:
        return CutoffDecision(True, sim, "embedding_equal")
    return CutoffDecision(llm.claims_equal(old_text, new_text), sim, "judge")


def _unique(sentences: list[str]) -> list[str]:
    seen, out = set(), []
    for s in sentences:
        if normalize(s) not in seen:
            seen.add(normalize(s))
            out.append(s)
    return out
