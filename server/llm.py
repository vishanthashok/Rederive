"""LLM providers for recipes, equivalence checks, and deletion checks.

FakeProvider is deterministic and offline. It interprets `params.fake` on a
recipe, so tests, scenarios, and the demo run without an API key.
AnthropicProvider sends the recipe template to Claude.
"""

import json
import re
from functools import lru_cache
from typing import Any, Protocol

from server.config import settings

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class LLMProvider(Protocol):
    def run_recipe(
        self,
        template: str,
        model: str,
        params: dict[str, Any],
        inputs: list[str],
        exclusions: list[str],
    ) -> str: ...

    def claims_equal(self, old: str, new: str) -> bool: ...

    def reveals(self, text: str, payload: str) -> bool: ...


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text.strip()) if s.strip()]


def normalize(text: str) -> str:
    """Lowercase and drop everything except letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sensitive_spans(text: str) -> list[str]:
    """Phone numbers and emails, used as extra deletion constraints."""
    return [m.group(0).strip() for m in PHONE_RE.finditer(text)] + EMAIL_RE.findall(text)


def render_prompt(template: str, inputs: list[str], exclusions: list[str]) -> str:
    numbered = "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(inputs))
    body = template.replace("{inputs}", numbered) if "{inputs}" in template else (
        f"{template}\n\nInputs:\n{numbered}"
    )
    if exclusions:
        banned = "\n".join(f"- {e}" for e in exclusions)
        body += (
            "\n\nThe following information was deleted by the user. Do not include it, "
            f"paraphrase it, or hint at it in any form:\n{banned}"
        )
    return body


class FakeProvider:
    """Deterministic stand-in for an LLM.

    Supported `params.fake.op` values:
      summarize  unique sentences of all inputs, in input order
      select     sentences matching `pattern`
      format     `template` filled with named `fields`, each the last regex
                 match (group 1) across inputs, or its `default`
    """

    def run_recipe(self, template, model, params, inputs, exclusions):
        spec = (params or {}).get("fake", {"op": "summarize"})
        op = spec.get("op", "summarize")
        sentences = _unique([s for text in inputs for s in split_sentences(text)])

        if op == "summarize":
            out = sentences
        elif op == "select":
            pattern = re.compile(spec["pattern"], re.I)
            out = [s for s in sentences if pattern.search(s)]
        elif op == "format":
            joined = " ".join(sentences)
            values = {}
            for name, field in spec["fields"].items():
                matches = re.findall(field["pattern"], joined, re.I)
                values[name] = matches[-1] if matches else field.get("default", "unknown")
            out = split_sentences(spec["template"].format(**values))
        else:
            raise ValueError(f"unknown fake op {op!r}")

        if exclusions:
            # A real model follows the exclusion instruction. The fake drops any
            # sentence that would fail the verifier.
            out = [s for s in out if not any(self.reveals(s, e) or _norm_hit(s, e) for e in exclusions)]
        text = " ".join(out)
        return text or spec.get("empty", "No information.")

    def claims_equal(self, old: str, new: str) -> bool:
        return {normalize(s) for s in split_sentences(old)} == {
            normalize(s) for s in split_sentences(new)
        }

    def reveals(self, text: str, payload: str) -> bool:
        # Paraphrase stand-in: any run of 4+ digits from the payload, such as
        # "ending in 0199", or the local part of an email.
        text_digits = re.sub(r"\D", " ", text)
        for group in re.findall(r"\d{4,}", payload):
            if re.search(rf"(?<!\d){group}(?!\d)", text_digits):
                return True
        for email in EMAIL_RE.findall(payload):
            if email.split("@")[0].lower() in text.lower():
                return True
        return False


class AnthropicProvider:
    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()

    def _text(self, **kwargs) -> str:
        response = self._client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            raise RuntimeError("model refused the request")
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _call(self, model: str, system: str, prompt: str, max_tokens: int) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if model.startswith("claude-haiku"):
            # Haiku 4.5 accepts sampling params. Sonnet 5 rejects them, so it
            # runs at low effort for stable, short outputs instead.
            kwargs["temperature"] = 0
        else:
            kwargs["output_config"] = {"effort": "low"}
        return self._text(**kwargs)

    def run_recipe(self, template, model, params, inputs, exclusions):
        target = settings.recipe_model if model in ("", "default") else model
        system = (
            "You maintain one record in an agent's long-term memory. Write only the "
            "record text, with no preamble. State facts plainly. Use only the inputs."
        )
        return self._call(
            target, system, render_prompt(template, inputs, exclusions),
            int(params.get("max_tokens", 2000)),
        )

    def claims_equal(self, old: str, new: str) -> bool:
        prompt = (
            "Two versions of a memory record follow. Does any factual claim differ "
            "between them? Ignore wording, order, and formatting.\n\n"
            f"<a>\n{old}\n</a>\n<b>\n{new}\n</b>\n\n"
            'Reply with JSON only: {"differs": true} or {"differs": false}.'
        )
        return not _json_flag(self._call(settings.judge_model, "You compare texts.", prompt, 50), "differs", True)

    def reveals(self, text: str, payload: str) -> bool:
        prompt = (
            "A user deleted some information. Check whether a text still reveals it, "
            "directly or by paraphrase.\n\n"
            f"<deleted>\n{payload}\n</deleted>\n<text>\n{text}\n</text>\n\n"
            'Reply with JSON only: {"reveals": true} or {"reveals": false}.'
        )
        return _json_flag(self._call(settings.judge_model, "You audit data deletion.", prompt, 50), "reveals", True)


def _json_flag(raw: str, key: str, default: bool) -> bool:
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return bool(json.loads(match.group(0))[key]) if match else default
    except (ValueError, KeyError):
        # Fail closed: an unparseable answer counts as "differs" / "reveals".
        return default


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = normalize(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _norm_hit(text: str, payload: str) -> bool:
    p = normalize(payload)
    return bool(p) and p in normalize(text)


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    if settings.llm == "anthropic":
        return AnthropicProvider()
    return FakeProvider()
