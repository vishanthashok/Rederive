"""Text helpers: embedding, sentence split, normalization, claim similarity.

Standard library only. These mirror server/embed.py, server/llm.py, and
server/cutoff.py in the main Rederive server, so the plugin and the server
make the same early-cutoff decisions. tests/plugin/test_parity.py checks that.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

DIM = 384
# Claim similarity at or above EQUAL_AT counts as the same content. Below
# DIFFERENT_BELOW counts as changed. The server sends the band between to a
# judge model. The plugin has no model of its own, so it treats the band as
# changed: an extra rebuild costs little, a missed one leaves wrong memory.
EQUAL_AT = 0.97
DIFFERENT_BELOW = 0.85


def embed(text: str) -> list[float]:
    """Hashed unigrams and bigrams in signed buckets, L2-normalized."""
    tokens = TOKEN_RE.findall(text.lower())
    features = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    vec = [0.0] * DIM
    for feat in features:
        h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
        bucket = int.from_bytes(h[:4], "little") % DIM
        vec[bucket] += 1.0 if h[4] & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text.strip()) if s.strip()]


def normalize(text: str) -> str:
    """Lowercase and drop everything except letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sensitive_spans(text: str) -> list[str]:
    """Phone numbers and emails, kept as extra deletion constraints."""
    return [m.group(0).strip() for m in PHONE_RE.finditer(text)] + EMAIL_RE.findall(text)


def _unique(sentences: list[str]) -> list[str]:
    seen, out = set(), []
    for s in sentences:
        if normalize(s) not in seen:
            seen.add(normalize(s))
            out.append(s)
    return out


def claim_similarity(old_text: str, new_text: str) -> float:
    """Weakest per-sentence match in either direction."""
    old = _unique(split_sentences(old_text))
    new = _unique(split_sentences(new_text))
    if not old or not new:
        return 1.0 if old == new else 0.0
    ov = [embed(s) for s in old]
    nv = [embed(s) for s in new]
    forward = min(max(cosine(a, b) for b in nv) for a in ov)
    backward = min(max(cosine(b, a) for a in ov) for b in nv)
    return min(forward, backward)


def decide(old_text: str, new_text: str) -> tuple[bool, float, str]:
    """Return (equal, similarity, method) for a rebuilt record."""
    if old_text.strip() == new_text.strip():
        return True, 1.0, "exact"
    sim = claim_similarity(old_text, new_text)
    if sim >= EQUAL_AT:
        return True, sim, "embedding_equal"
    if sim < DIFFERENT_BELOW:
        return False, sim, "embedding_different"
    return False, sim, "uncertain_treated_as_changed"


def reveals(text: str, payload: str) -> str | None:
    """Why `text` still reveals deleted `payload`, or None if it does not."""
    if payload.lower() in text.lower():
        return "exact"
    p = normalize(payload)
    if p and p in normalize(text):
        return "normalized"
    # Paraphrase stand-ins: a run of 4+ digits from the payload ("ending in
    # 0199"), or the local part of an email address.
    text_digits = re.sub(r"\D", " ", text)
    for group in re.findall(r"\d{4,}", payload):
        if re.search(rf"(?<!\d){group}(?!\d)", text_digits):
            return "digits"
    for email in EMAIL_RE.findall(payload):
        if email.split("@")[0].lower() in text.lower():
            return "email"
    # The server asks a judge model about paraphrases. The plugin has none, so
    # it flags a sentence that repeats most of a deleted sentence's content
    # words, such as "Manager is Priya." after "My manager is Priya." was
    # deleted. It errs toward blocking.
    text_sentences = [set(TOKEN_RE.findall(s.lower())) for s in split_sentences(text)]
    for sentence in split_sentences(payload):
        key = content_words(sentence)
        if not key:
            continue
        for words in text_sentences:
            if len(key & words) >= math.ceil(0.75 * len(key)):
                return "paraphrase"
    return None


STOPWORDS = frozenset(
    "a an and are as at be been but by do does for from had has have he her his i if in into is it "
    "its me my of on or our she so that the their them they this to was we were what when where "
    "which who will with you your user users".split()
)


def content_words(sentence: str) -> set[str]:
    return {w for w in TOKEN_RE.findall(sentence.lower()) if w not in STOPWORDS and len(w) > 1}


def recipe_hash(template: str, model: str, params: dict | None = None) -> str:
    canonical = json.dumps(
        {"template": template, "model": model, "params": params or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
