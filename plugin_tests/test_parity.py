"""The plugin's text helpers must match the server's, so both make the same cutoff calls."""

import json
from pathlib import Path

import pytest
from rederive_local import text as T

server_embed = pytest.importorskip("server.embed")
server_cutoff = pytest.importorskip("server.cutoff")
server_llm = pytest.importorskip("server.llm")
server_recipes = pytest.importorskip("rederive.recipes")

PAIRS = Path(__file__).resolve().parent.parent / "eval" / "cutoff_pairs.jsonl"


def pairs():
    return [json.loads(line) for line in PAIRS.read_text().splitlines() if line.strip()]


def test_embedding_matches_server():
    e = server_embed.HashingEmbedder()
    for text in ["User works at Initech.", "Dana Lee is a data engineer on the platform team.", ""]:
        assert T.embed(text) == e.embed(text)


def test_claim_similarity_matches_server_on_labeled_pairs():
    e = server_embed.HashingEmbedder()
    for p in pairs():
        old, new = p["old"], p["new"]
        assert T.claim_similarity(old, new) == pytest.approx(server_cutoff.claim_similarity(old, new, e))


def test_thresholds_match_server_defaults():
    from server.config import settings

    assert T.EQUAL_AT == settings.cutoff_equal
    assert T.DIFFERENT_BELOW == settings.cutoff_different


def test_helpers_match_server():
    for s in ["One. Two! Three? Four", "Call 512-555-0199 or dana@example.com."]:
        assert T.split_sentences(s) == server_llm.split_sentences(s)
        assert T.normalize(s) == server_llm.normalize(s)
        assert T.sensitive_spans(s) == server_llm.sensitive_spans(s)
    assert T.recipe_hash("t", "m", {"a": 1}) == server_recipes.recipe_hash("t", "m", {"a": 1})
