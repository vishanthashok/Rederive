"""Deletion verifier: check text against must_not_contain constraints."""

from dataclasses import asdict, dataclass

from server.llm import LLMProvider, normalize


@dataclass(frozen=True)
class CheckResult:
    constraint_id: str
    payload: str
    exact_hit: bool
    normalized_hit: bool
    paraphrase_hit: bool

    @property
    def violated(self) -> bool:
        return self.exact_hit or self.normalized_hit or self.paraphrase_hit

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("payload")
        d["violated"] = self.violated
        return d


def check(text: str, constraints: list[dict], llm: LLMProvider) -> list[CheckResult]:
    results = []
    for c in constraints:
        payload = c["payload"]
        exact = payload.lower() in text.lower()
        norm_payload = normalize(payload)
        normalized = bool(norm_payload) and norm_payload in normalize(text)
        # Skip the LLM call when a cheaper check already caught it.
        paraphrase = False if (exact or normalized) else llm.reveals(text, payload)
        results.append(CheckResult(str(c["id"]), payload, exact, normalized, paraphrase))
    return results


def violations(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.violated]
