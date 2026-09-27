import pytest

from rederive import RederiveError, recipe_hash
from server.db import queries as q
from tests.helpers import EMPLOYER, SUMMARY


def test_observe_and_read(api):
    rec = api.observe("I live in Austin.", user="dana")
    got = api.read(rec["id"])
    assert got["text"] == "I live in Austin."
    assert got["version"] == 1 and got["status"] == "valid" and got["kind"] == "observation"
    assert got["meta"] == {"user": "dana"}


def test_derive_records_edges_and_recipe(api, pool):
    a = api.observe("I work at Globex.")
    b = api.observe("I like email.")
    s = api.derive([a, b], SUMMARY, kind="summary")
    got = api.read(s["id"])
    assert got["text"] == "I work at Globex. I like email."
    assert got["recipe_hash"] == SUMMARY.hash
    with pool.connection() as conn:
        stored = q.get_recipe(conn, SUMMARY.hash)
        assert recipe_hash(stored["template"], stored["model"], stored["params"]) == SUMMARY.hash
        parents = {str(e["parent_id"]) for e in q.parent_edges(conn, s["id"], 1)}
    assert parents == {a["id"], b["id"]}


def test_descendants_in_topological_order(api, pool):
    # a -> s1 -> s2 -> s3, and a -> s3 directly. s3 must come after s2.
    a = api.observe("I work at Globex.")
    s1 = api.derive([a], SUMMARY)
    s2 = api.derive([s1], SUMMARY)
    s3 = api.derive([s2, a], SUMMARY)
    with pool.connection() as conn:
        rows = q.descendants(conn, a["id"], [1])
    order = [str(r["id"]) for r in rows]
    assert order == [s1["id"], s2["id"], s3["id"]]
    assert [r["depth"] for r in rows] == [1, 2, 3]


def test_lineage_returns_ancestor_tree(api):
    a = api.observe("I work at Globex.")
    b = api.observe("I am on Central time.")
    s = api.derive([a, b], SUMMARY)
    e = api.derive([s], EMPLOYER, kind="belief")
    lin = api.lineage(e["id"])
    assert lin["root"] == f"{e['id']}@1"
    assert set(lin["nodes"]) == {f"{x['id']}@1" for x in (a, b, s, e)}
    depths = {(ed["child_id"], ed["parent_id"]): ed["depth"] for ed in lin["edges"]}
    assert depths[(e["id"], s["id"])] == 1
    assert depths[(s["id"], a["id"])] == 2


def test_derive_rejects_cycles(api):
    a = api.observe("I work at Globex.")
    s = api.derive([a], SUMMARY)
    child = api.derive([s], SUMMARY)
    # A new version of s built from its own descendant would form a loop.
    with pytest.raises(RederiveError) as err:
        api.derive([child], SUMMARY, target_id=s["id"])
    assert err.value.status == 409
    with pytest.raises(RederiveError) as err:
        api.derive([s], SUMMARY, target_id=s["id"])
    assert err.value.status == 409


def test_reflection_versions_stay_acyclic(api):
    a = api.observe("I work at Globex.")
    r1 = api.derive([a], SUMMARY, kind="reflection")
    r2 = api.derive([r1, a], SUMMARY, kind="reflection")  # reflection v2 reads v1
    assert r2["id"] != r1["id"]


def test_derive_rejects_retracted_or_stale_inputs(api):
    a = api.observe("I work at Globex.")
    s = api.derive([a], SUMMARY)
    api.retract(a["id"])
    with pytest.raises(RederiveError) as err:
        api.derive([a], SUMMARY)
    assert err.value.status == 410
    with pytest.raises(RederiveError) as err:
        api.derive([s], SUMMARY)
    assert err.value.status == 409


def test_derive_with_new_version_of_target(api, run_jobs):
    a = api.observe("I work at Globex.")
    b = api.observe("I work at Initech.")
    s = api.derive([a], SUMMARY)
    child = api.derive([s], SUMMARY)
    out = api.derive([b], SUMMARY, target_id=s["id"])
    assert out["version"] == 2 and out["stale_count"] == 1
    run_jobs()
    assert api.read(child["id"])["text"] == "I work at Initech."
