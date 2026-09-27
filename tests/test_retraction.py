from server.db import queries as q
from server.embed import get_embedder
from server.llm import FakeProvider
from server.memory import correct
from server.workers.rebuild import drain
from tests.helpers import EMPLOYER, SUMMARY, TIMEZONE


def build_profile(api):
    m1 = api.observe("I work at Globex.")
    m2 = api.observe("I am on Central time.")
    m3 = api.observe("I started working at Initech in March.")
    work = api.derive([m1, m3], SUMMARY)
    employer = api.derive([work], EMPLOYER, kind="belief")
    tz = api.derive([m2], TIMEZONE, kind="belief")
    profile = api.derive([employer, tz], SUMMARY)
    return dict(m1=m1, m2=m2, m3=m3, work=work, employer=employer, tz=tz, profile=profile)


def test_retract_marks_descendants_stale(api):
    g = build_profile(api)
    out = api.retract(g["m1"]["id"])
    assert out["stale_count"] == 3
    assert [s["id"] for s in out["stale"]] == [g["work"]["id"], g["employer"]["id"], g["profile"]["id"]]
    assert api.read(g["work"]["id"])["status"] == "stale"
    assert api.read(g["tz"]["id"])["status"] == "valid"
    assert api.read(g["m1"]["id"])["status"] == "retracted"


def test_rebuild_with_early_cutoff(api, run_jobs):
    g = build_profile(api)
    api.retract(g["m1"]["id"])
    counts = run_jobs()
    # work changes, employer rebuilds to the same text, profile never reruns.
    assert counts == {"done": 1, "cut_off": 1, "skipped": 1}

    work = api.read(g["work"]["id"])
    assert work["version"] == 2 and work["text"] == "I started working at Initech in March."
    employer = api.read(g["employer"]["id"])
    assert employer["version"] == 2 and employer["text"] == "User works at Initech."
    assert [v["status"] for v in api.versions(g["employer"]["id"])] == ["equivalent", "valid"]
    profile = api.read(g["profile"]["id"])
    assert profile["version"] == 1 and profile["status"] == "valid"

    # The profile now reaches employer v2 through an alias edge.
    lin = api.lineage(g["profile"]["id"])
    alias = [e for e in lin["edges"] if e["alias"]]
    assert [(e["parent_id"], e["parent_version"]) for e in alias] == [(g["employer"]["id"], 2)]
    parents = {(e["parent_id"], e["parent_version"]) for e in lin["edges"] if e["depth"] == 1}
    assert parents == {(g["employer"]["id"], 2), (g["tz"]["id"], 1)}


def test_correct_rebuilds_with_new_text(api, run_jobs):
    g = build_profile(api)
    out = api.correct(g["m3"]["id"], "I started working at Hooli in March.")
    assert out["version"] == 2 and out["stale_count"] == 3
    run_jobs()
    assert api.read(g["employer"]["id"])["text"] == "User works at Hooli."
    profile = api.read(g["profile"]["id"])
    assert profile["version"] == 2
    assert "Hooli" in profile["text"]
    d = api.diff(g["profile"]["id"], 1, 2)
    assert "-User works at Initech." in d["unified"]
    assert "+User works at Hooli." in d["unified"]


def test_retracting_all_inputs_retracts_child(api, run_jobs):
    a = api.observe("I work at Globex.")
    s = api.derive([a], SUMMARY)
    child = api.derive([s], SUMMARY)
    api.retract(a["id"])
    run_jobs()
    assert api.read(s["id"])["status"] == "retracted"
    assert api.read(child["id"])["status"] == "retracted"


def test_second_retraction_supersedes_queued_job(api, pool, run_jobs):
    g = build_profile(api)
    first = api.retract(g["m1"]["id"])
    second = api.correct(g["m3"]["id"], "I started working at Hooli in March.")
    with pool.connection() as conn:
        states = {
            r["id"]: r["state"]
            for r in conn.execute("SELECT id, state FROM rebuild_job").fetchall()
        }
    assert all(states[j] == "discarded" for j in first["job_ids"])
    assert all(states[j] == "queued" for j in second["job_ids"])
    run_jobs()
    assert api.read(g["employer"]["id"])["text"] == "User works at Hooli."


class RacingProvider(FakeProvider):
    """Fires a second invalidation while the worker is mid-rebuild."""

    def __init__(self, pool, record_id):
        self.pool, self.record_id, self.fired = pool, record_id, False

    def run_recipe(self, *args, **kwargs):
        if not self.fired:
            self.fired = True
            with self.pool.connection() as conn:
                correct(conn, self.record_id, "I started working at Hooli in March.", get_embedder())
        return super().run_recipe(*args, **kwargs)


def test_late_worker_output_is_discarded(api, pool):
    g = build_profile(api)
    api.retract(g["m1"]["id"])
    racing = RacingProvider(pool, g["m3"]["id"])
    counts = drain(pool, llm=racing)
    # The first rebuild of `work` finished after the correction bumped the
    # fence token, so its output was thrown away and a fresh job won.
    assert counts.get("discarded", 0) >= 1
    work_versions = api.versions(g["work"]["id"])
    assert len(work_versions) == 2
    assert api.read(g["work"]["id"])["text"] == "I started working at Hooli in March."
    assert api.read(g["employer"]["id"])["text"] == "User works at Hooli."
    with pool.connection() as conn:
        head = q.get_head(conn, g["work"]["id"])
    assert head["latest_version"] == 2
