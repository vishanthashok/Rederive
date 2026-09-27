import math

from rederive import exposed, tool_call
from server.llm import FakeProvider
from server.workers.rebuild import drain
from tests.helpers import SUMMARY
from tests.test_retraction import build_profile


class CountingProvider(FakeProvider):
    def __init__(self):
        self.input_sizes = []

    def run_recipe(self, template, model, params, inputs, exclusions):
        self.input_sizes.append(len(inputs))
        return super().run_recipe(template, model, params, inputs, exclusions)


def test_fan_in_tree_rebuilds_log_n_nodes(api, pool):
    n, k = 64, 4
    leaves = [api.observe(f"Fact number {i}.") for i in range(n)]
    out = api.derive(leaves, SUMMARY, fan_in_k=k)
    assert len(out["partial_ids"]) == 16 + 4
    top = api.read(out["id"])
    assert top["meta"]["fan_in"] == {"k": k, "leaves": n, "levels": 3}
    assert "Fact number 63." in top["text"]

    retracted = api.retract(leaves[17]["id"])
    assert retracted["stale_count"] == math.ceil(math.log(n, k))

    llm = CountingProvider()
    drain(pool, llm=llm)
    assert len(llm.input_sizes) == 3
    assert max(llm.input_sizes) <= k
    assert "Fact number 17." not in api.read(out["id"])["text"]


def test_exposure_report_lists_calls_that_read_invalid_versions(api, run_jobs):
    g = build_profile(api)

    @exposed(api)
    def draft_reply():
        return api.read(g["work"]["id"])["text"], api.read(g["tz"]["id"])["text"]

    draft_reply()
    call_id = draft_reply.last_call.id
    assert api.exposures(stale_only=True) == []

    api.retract(g["m1"]["id"])
    pending = api.exposures(stale_only=True)
    assert [(r["tool_call_id"], r["record_id"], r["state"]) for r in pending] == [
        (call_id, g["work"]["id"], "pending")
    ]

    run_jobs()
    report = api.exposures(stale_only=True)
    assert len(report) == 1
    row = report[0]
    assert row["tool_name"] == "draft_reply" and row["state"] == "invalid"
    assert row["read_text"] == "I work at Globex. I started working at Initech in March."
    assert row["latest_version"] == 2

    everything = api.exposures(stale_only=False)
    assert {r["record_id"] for r in everything} == {g["work"]["id"], g["tz"]["id"]}


def test_reads_after_cutoff_stay_valid(api, run_jobs):
    g = build_profile(api)
    with tool_call("lookup_profile"):
        api.read(g["employer"]["id"])
        api.read(g["profile"]["id"])
    api.retract(g["m1"]["id"])
    run_jobs()
    # employer was rebuilt to an equivalent version and profile never changed.
    assert api.exposures(stale_only=True) == []
