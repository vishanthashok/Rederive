"""Tune early-cutoff thresholds on hand-labeled rebuild pairs.

    python eval/tune_cutoff.py                 # fake judge, hashing embedder
    REDERIVE_LLM=anthropic python eval/tune_cutoff.py

For each (equal_at, different_below) pair on a grid, runs server.cutoff.decide
over eval/cutoff_pairs.jsonl and reports:
  false-equal rate      labeled different, judged equal (a missed rebuild)
  false-different rate  labeled equal, judged different (a wasted rebuild)
  judge calls           pairs that fell in the middle band

A false-equal leaves wrong content in memory, so the pick minimizes it first,
then false-different, then judge calls.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "sdk")]

from server.cutoff import decide  # noqa: E402
from server.embed import get_embedder  # noqa: E402
from server.llm import get_llm  # noqa: E402

PAIRS = Path(__file__).with_name("cutoff_pairs.jsonl")


class CachedJudge:
    """Wraps the LLM so each pair hits the judge at most once across the grid."""

    def __init__(self, llm):
        self.llm, self.cache, self.calls = llm, {}, 0

    def claims_equal(self, old, new):
        self.calls += 1
        if (old, new) not in self.cache:
            self.cache[(old, new)] = self.llm.claims_equal(old, new)
        return self.cache[(old, new)]


def evaluate(pairs, emb, judge, equal_at, different_below):
    fe = fd = calls = 0
    for p in pairs:
        before = judge.calls
        d = decide(p["old"], p["new"], emb, judge, equal_at, different_below)
        calls += judge.calls - before
        fe += (not p["equal"]) and d.equal
        fd += p["equal"] and not d.equal
    n_diff = sum(not p["equal"] for p in pairs)
    n_eq = len(pairs) - n_diff
    return {"equal_at": equal_at, "different_below": different_below,
            "false_equal": fe / n_diff, "false_different": fd / n_eq, "judge_calls": calls}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", type=int, default=8, help="rows of the grid to print")
    args = parser.parse_args()

    pairs = [json.loads(line) for line in PAIRS.read_text().splitlines() if line.strip()]
    emb = get_embedder()
    judge = CachedJudge(get_llm())

    grid = []
    for equal_at in (0.90, 0.93, 0.95, 0.97, 0.98, 0.99, 1.01):
        for different_below in (0.5, 0.6, 0.7, 0.75, 0.8, 0.85):
            if different_below < equal_at:
                grid.append(evaluate(pairs, emb, judge, equal_at, different_below))
    grid.sort(key=lambda r: (r["false_equal"], r["false_different"], r["judge_calls"]))

    print(f"{len(pairs)} pairs ({sum(p['equal'] for p in pairs)} equal)")
    print(f"{'equal_at':>9} {'diff_below':>10} {'false_eq':>9} {'false_diff':>10} {'judge':>6}")
    for r in grid[: args.show]:
        print(f"{r['equal_at']:>9.2f} {r['different_below']:>10.2f} {r['false_equal']:>9.1%} "
              f"{r['false_different']:>10.1%} {r['judge_calls']:>6}")
    default = evaluate(pairs, emb, judge, 0.97, 0.85)
    print(f"\ndefault 0.97/0.85: false-equal {default['false_equal']:.1%}, "
          f"false-different {default['false_different']:.1%}, judge calls {default['judge_calls']}")
    best = grid[0]
    print(f"pick: REDERIVE_CUTOFF_EQUAL={best['equal_at']} REDERIVE_CUTOFF_DIFFERENT={best['different_below']}")


if __name__ == "__main__":
    main()
