import pytest

from rederive import Recipe, RecipeRegistry, recipe_hash
from server.cutoff import decide
from server.embed import HashingEmbedder, cosine
from server.llm import FakeProvider, sensitive_spans

emb = HashingEmbedder()


def _decide(a, b, **kw):
    return decide(a, b, emb, FakeProvider(), **kw)


def test_cutoff_exact_and_reorder():
    assert _decide("User works at Initech.", "User works at Initech. ").method == "exact"
    d = _decide("User works at Initech. User is on Central time.",
                "User is on Central time. User works at Initech.")
    assert d.equal


def test_cutoff_band_goes_to_judge():
    d = _decide("User works at Globex. User is on Central time.",
                "User works at Initech. User is on Central time.", equal_at=0.97, different_below=0.1)
    assert d.method == "judge" and not d.equal


def test_claim_similarity_catches_small_edits_in_long_text():
    facts = [f"User fact number {i} is about topic {i}." for i in range(10)]
    old = " ".join(facts)
    swapped = old.replace("topic 4", "topic 44")
    dropped = " ".join(f for i, f in enumerate(facts) if i != 7)
    whole_text = cosine(emb.embed(old), emb.embed(swapped))
    assert whole_text > 0.97  # document cosine would call this equal
    for new in (swapped, dropped):
        d = _decide(old, new)
        assert d.similarity < 0.97 and not d.equal


def test_cutoff_low_similarity_is_different():
    d = _decide("User prefers email.", "Order 1142 shipped on May 3.")
    assert d.method == "embedding_different" and not d.equal


def test_recipe_hash_is_stable_and_order_independent():
    a = Recipe("t", "m", {"x": 1, "y": 2})
    b = Recipe("t", "m", {"y": 2, "x": 1})
    assert a.hash == b.hash == recipe_hash("t", "m", {"x": 1, "y": 2})
    assert Recipe("t", "m", {"x": 2}).hash != a.hash


def test_recipe_registry_rejects_conflicting_names():
    reg = RecipeRegistry()
    reg.register("summary", Recipe("t"))
    reg.register("summary", Recipe("t"))
    with pytest.raises(ValueError):
        reg.register("summary", Recipe("other"))


def test_fake_format_uses_last_match():
    llm = FakeProvider()
    params = {"fake": {"op": "format", "template": "User works at {e}.",
                       "fields": {"e": {"pattern": r"work(?:s|ing)? at ([A-Z]\w+)"}}}}
    out = llm.run_recipe("t", "m", params, ["I work at Globex.", "Now working at Initech."], [])
    assert out == "User works at Initech."


def test_sensitive_spans():
    assert sensitive_spans("Call 512-555-0199 or mail dana@example.com.") == [
        "512-555-0199", "dana@example.com"]
