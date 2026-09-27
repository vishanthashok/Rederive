"""Semantic early cutoff: decide whether a rebuilt record says the same thing.

Order of checks:
  1. identical text                      -> equal
  2. cosine below `different_below`      -> different
  3. cosine at or above `equal_at` and the same number of sentences -> equal
  4. otherwise ask the judge model whether any claim differs

The sentence-count guard in step 3 exists because cosine is blind to one
dropped fact in a long summary: removing 1 of 16 facts still scores about
0.998 with the hashing embedder. Those cases go to the judge.
"""

from dataclasses import dataclass

from server.config import settings
from server.embed import cosine
from server.llm import LLMProvider, split_sentences


@dataclass(frozen=True)
class CutoffDecision:
    equal: bool
    similarity: float
    method: str  # exact | embedding_equal | embedding_different | judge


def decide(
    old_text: str,
    new_text: str,
    old_vec: list[float] | None,
    new_vec: list[float] | None,
    llm: LLMProvider,
    equal_at: float | None = None,
    different_below: float | None = None,
) -> CutoffDecision:
    equal_at = settings.cutoff_equal if equal_at is None else equal_at
    different_below = settings.cutoff_different if different_below is None else different_below

    if old_text.strip() == new_text.strip():
        return CutoffDecision(True, 1.0, "exact")
    sim = cosine(old_vec, new_vec)
    if sim < different_below:
        return CutoffDecision(False, sim, "embedding_different")
    if sim >= equal_at and len(split_sentences(old_text)) == len(split_sentences(new_text)):
        return CutoffDecision(True, sim, "embedding_equal")
    return CutoffDecision(llm.claims_equal(old_text, new_text), sim, "judge")
