"""Run scenario YAML files against a live Rederive server.

    python eval/run_scenarios.py                       # all scenarios/*.yaml
    python eval/run_scenarios.py scenarios/delete_phone.yaml --url http://localhost:8000

The server needs REDERIVE_ALLOW_RESET=1 and a running worker. Exact-text
checks assume REDERIVE_LLM=fake. Each scenario starts from an empty store.

Step types:
  observe   {key, text, **meta}
  derive    {key, inputs: [keys] | "prefix*", recipe, kind, fan_in_k}
  tool_call {demo: tool name, ...args} or {name, reads: [keys]}
  retract   key
  correct   {key, text}
  delete    key or {key, payload}
  wait      {}   waits for the worker, then compares job states of the
                 previous invalidation
  check     {...} assertions on current state
Any step can carry `expect` for the result of its action.
"""

import argparse
import fnmatch
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from demo_agent.support_agent import SupportAgent  # noqa: E402
from rederive import Recipe, Rederive, RederiveError, tool_call  # noqa: E402
from server.llm import normalize  # noqa: E402


class ScenarioFailure(AssertionError):
    pass


def ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise ScenarioFailure(msg)


class Runner:
    def __init__(self, client: Rederive, spec: dict):
        self.client = client
        self.spec = spec
        self.ids: dict[str, dict] = {}
        self.agent: SupportAgent | None = None
        self.recipes = {name: Recipe(r["template"], r.get("model", "default"), r.get("params", {}))
                        for name, r in (spec.get("recipes") or {}).items()}
        self.last_jobs: list[int] = []
        self.log: list[str] = []

    # -- seeding ------------------------------------------------------------

    def seed(self) -> None:
        seed = self.spec.get("seed")
        if seed == "demo":
            self.agent = SupportAgent(self.client)
            self.ids = self.agent.seed()
        elif isinstance(seed, dict):
            obs = seed.get("observations", {})
            for i in range(obs.get("count", 0)):
                self.ids[obs["key"].format(i=i)] = self.client.observe(obs["text"].format(i=i))
            for item in seed.get("items", []):
                self.ids[item["key"]] = self.client.observe(item["text"])
        n = len(self.client.graph()["nodes"])
        self.log.append(f"seeded {n} records")

    # -- steps --------------------------------------------------------------

    def keys(self, pattern) -> list[str]:
        if isinstance(pattern, list):
            return pattern
        return [k for k in self.ids if fnmatch.fnmatch(k, pattern)]

    def rid(self, key: str) -> str:
        ensure(key in self.ids, f"unknown key {key!r}")
        return self.ids[key]["id"]

    def run_step(self, step: dict) -> None:
        expect = step.get("expect", {})
        action = next(k for k in step if k != "expect")
        arg = step[action]
        result = getattr(self, f"do_{action}")(arg)
        if isinstance(result, dict) and "job_ids" in result:
            self.last_jobs = result["job_ids"]
        self.expect(action, result, expect)

    def do_observe(self, arg: dict) -> dict:
        meta = {k: v for k, v in arg.items() if k not in ("key", "text")}
        self.ids[arg["key"]] = self.client.observe(arg["text"], **meta)
        return self.ids[arg["key"]]

    def do_derive(self, arg: dict) -> dict:
        recipe = self.recipes[arg["recipe"]]
        inputs = [self.ids[k] for k in self.keys(arg["inputs"])]
        out = self.client.derive(inputs, recipe, kind=arg.get("kind", "summary"),
                                 fan_in_k=arg.get("fan_in_k"), name=arg["key"])
        self.ids[arg["key"]] = out
        return out

    def do_tool_call(self, arg: dict) -> dict:
        if "demo" in arg:
            ensure(self.agent is not None, "demo tools need seed: demo")
            fn = getattr(self.agent, arg["demo"])
            fn(*[v for k, v in arg.items() if k != "demo"])
            return {"reads": fn.last_call.reads}
        with tool_call(arg["name"]) as call:
            for key in arg.get("reads", []):
                self.client.read(self.rid(key))
        return {"reads": call.reads}

    def do_retract(self, key: str) -> dict:
        return self.client.retract(self.rid(key))

    def do_correct(self, arg: dict) -> dict:
        return self.client.correct(self.rid(arg["key"]), arg["text"])

    def do_delete(self, arg) -> dict:
        key, payload = (arg, None) if isinstance(arg, str) else (arg["key"], arg.get("payload"))
        return self.client.delete(self.rid(key), payload)

    def do_wait(self, arg: dict) -> dict:
        self.client.wait_idle(timeout=arg.get("timeout", 120))
        wanted = set(self.last_jobs)
        states = Counter(j["state"] for j in self.client.jobs()["jobs"] if j["id"] in wanted)
        self.log.append(f"jobs: {dict(states)}")
        return {"jobs": dict(states)}

    def do_check(self, arg: dict) -> dict:
        c = self.client
        text = lambda key: c.read(self.rid(key))["text"]  # noqa: E731
        for key, want in (arg.get("text_equals") or {}).items():
            got = text(key)
            ensure(got == want, f"{key}: expected {want!r}, got {got!r}")
        for key, want in (arg.get("contains") or {}).items():
            ensure(want in text(key), f"{key} should contain {want!r}")
        for key, want in (arg.get("not_contains") or {}).items():
            ensure(want not in text(key), f"{key} should not contain {want!r}")
        for key, want in (arg.get("not_contains_normalized") or {}).items():
            ensure(normalize(want) not in normalize(text(key)), f"{key} leaks {want!r}")
        for key, want in (arg.get("version") or {}).items():
            got = c.read(self.rid(key))["version"]
            ensure(got == want, f"{key}: expected v{want}, got v{got}")
        for key, want in (arg.get("status") or {}).items():
            got = c.versions(self.rid(key))[-1]["status"]
            ensure(got == want, f"{key}: expected status {want}, got {got}")
        for key, want in (arg.get("meta") or {}).items():
            meta = c.read(self.rid(key))["meta"]
            for mk, mv in want.items():
                ensure(meta.get(mk) == mv, f"{key}.meta.{mk}: expected {mv}, got {meta.get(mk)}")
        for key in arg.get("unreadable") or []:
            try:
                c.read(self.rid(key))
                raise ScenarioFailure(f"{key} should be unreadable")
            except RederiveError as err:
                ensure(err.status == 410, f"{key}: expected 410, got {err.status}")
        if "exposure_stale_tools" in arg:
            tools = {r["tool_name"] for r in c.exposures(stale_only=True)}
            for name in arg["exposure_stale_tools"]:
                ensure(name in tools, f"exposure report should list {name}, got {sorted(tools)}")
        if arg.get("exposure_clean"):
            stale = c.exposures(stale_only=True)
            ensure(not stale, f"expected no stale exposures, got {len(stale)}")
        if "deletion_report" in arg:
            spec = arg["deletion_report"]
            report = c.deletion_report(self.rid(spec["source"]))
            for key in spec.get("caught_on_first_attempt", []):
                hit = [ch for ch in report["checks"] if ch["record_id"] == self.rid(key)
                       and ch["attempt"] == 1 and (ch["exact_hit"] or ch["normalized_hit"] or ch["paraphrase_hit"])]
                ensure(bool(hit), f"verifier should have caught a leak in {key} on attempt 1")
            if "residual" in spec:
                got = {r["id"] for r in report["residual"]}
                want = {self.rid(k) for k in spec["residual"]}
                ensure(got == want, f"residual sources: expected {want}, got {got}")
        return {}

    def expect(self, action: str, result: dict, expect: dict) -> None:
        if "stale_count" in expect:
            ensure(result["stale_count"] == expect["stale_count"],
                   f"{action}: expected stale_count {expect['stale_count']}, got {result['stale_count']}")
        if "stale_count_min" in expect:
            ensure(result["stale_count"] >= expect["stale_count_min"],
                   f"{action}: expected stale_count >= {expect['stale_count_min']}, got {result['stale_count']}")
        if "stale_count" in result:
            self.log.append(f"{action}: {result['stale_count']} stale")
        if "jobs" in expect:
            got = result["jobs"]
            ensure(got == expect["jobs"], f"{action}: expected jobs {expect['jobs']}, got {got}")
        for state in expect.get("jobs_none", []):
            ensure(not result["jobs"].get(state), f"{action}: unexpected {state} jobs: {result['jobs']}")


def run_file(client: Rederive, path: Path) -> tuple[bool, float, list[str]]:
    spec = yaml.safe_load(path.read_text())
    runner = Runner(client, spec)
    start = time.monotonic()
    try:
        client.reset()
        runner.seed()
        for step in spec["steps"]:
            runner.run_step(step)
        return True, time.monotonic() - start, runner.log
    except ScenarioFailure as err:
        return False, time.monotonic() - start, runner.log + [f"FAIL: {err}"]
    except Exception:  # noqa: BLE001
        return False, time.monotonic() - start, runner.log + ["ERROR:", traceback.format_exc()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args(argv)
    files = args.files or sorted((ROOT / "scenarios").glob("*.yaml"))

    client = Rederive(args.url)
    results = []
    for path in files:
        ok, secs, log = run_file(client, path)
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {path.stem:<18} {secs:5.1f}s  " + " | ".join(log[:6]))
        if not ok:
            print("      " + "\n      ".join(log[6:] or log[-1:]))
    print(f"\n{sum(results)}/{len(results)} scenarios passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
