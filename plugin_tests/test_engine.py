import pytest
from rederive_local.engine import RederiveError


def names(queue):
    return [t["name"] for t in queue]


def test_retract_cascades_in_dependency_order(engine, story):
    out = engine.retract(story["globex"])
    # employer, profile, renewal_outreach go stale. manager and timezone do not.
    assert out["stale_count"] == 3
    # Only employer is ready: profile and renewal_outreach wait for it.
    assert names(out["rebuild_queue"]) == ["employer"]
    task = out["rebuild_queue"][0]
    assert [i["text"] for i in task["inputs"]] == ["I started working at Initech in March."]
    assert task["previous_text"] == "User works at Globex."
    assert task["instruction"].startswith("Where does the user work now?")

    out = engine.rebuild("employer", "User works at Initech.")
    assert out["method"] == "embedding_different"
    assert sorted(names(out["rebuild_queue"])) == ["profile", "renewal_outreach"]
    profile = next(t for t in out["rebuild_queue"] if t["name"] == "profile")
    assert "User works at Initech." in [i["text"] for i in profile["inputs"]]

    engine.rebuild("profile", "User works at Initech. User's manager is Priya. User is on Central time.")
    out = engine.rebuild("renewal_outreach", "Before renewal, contact Priya at Initech.")
    assert out["rebuild_queue"] == []
    assert out["tally"] == {"waiting_for_rewrite": 0, "done": 3}

    hist = engine.history("profile")
    assert [v["status"] for v in hist["versions"]] == ["superseded", "valid"]
    assert hist["last_change"] == ["-User works at Globex.", "+User works at Initech."]


def test_equivalent_rebuild_cuts_off_the_cascade(engine, story):
    engine.correct(story["manager"], "My manager is Priya!")
    out = engine.pending()
    assert names(out) == ["manager"]
    # Same claim, same words: the cascade stops, so the profile never rebuilds.
    out = engine.rebuild("manager", "User's manager is Priya.")
    assert out["method"] == "exact"
    assert out["rebuild_queue"] == []
    assert out["tally"]["cut_off"] == 1
    assert out["tally"]["skipped"] == 2  # profile and renewal_outreach
    assert engine.recall(ref="profile")["memories"][0]["status"] == "valid"
    assert engine.recall(ref="profile")["memories"][0]["version"] == 1


def test_record_with_no_inputs_left_is_retracted(engine):
    a = engine.remember("I like tea.")
    engine.derive([a["id"]], "Drinks the user likes.", "User likes tea.", kind="belief", name="drinks")
    out = engine.retract(a["id"])
    assert out["rebuild_queue"] == []
    assert out["tally"]["done"] == 1
    assert engine.recall(ref="drinks")["memories"][0]["status"] == "retracted"


def test_forget_blocks_leaks_and_reports_mentions(engine, story):
    also = engine.remember("Call me at 512-555-0199 after 10am.")
    out = engine.forget(story["phone"])
    assert names(out["rebuild_queue"]) == ["contact_plan"]
    assert [m["id"] for m in out["still_mentioned_in"]] == [also["id"]]
    with pytest.raises(RederiveError, match="deleted"):
        engine.rebuild("contact_plan", "Text the number ending in 0199 during Central hours.")
    out = engine.rebuild("contact_plan", "Email the user during Central business hours.")
    assert out["rebuild_queue"] == []
    with pytest.raises(RederiveError, match="deleted"):
        engine.recall(ref=story["phone"])
    # New derived memories are checked too.
    with pytest.raises(RederiveError, match="deleted"):
        engine.derive([story["tz"]], "Contact notes.", "Phone 5125550199, Central time.", name="notes")


def test_forget_catches_paraphrase(engine, story):
    out = engine.forget(story["manager"])
    # The manager belief lost its only input, so it is retracted with no rewrite.
    assert sorted(names(out["rebuild_queue"])) == ["profile", "renewal_outreach"]
    with pytest.raises(RederiveError, match="paraphrase match"):
        engine.rebuild("profile", "User works at Globex. Manager is Priya. User is on Central time.")
    engine.rebuild("profile", "User works at Globex. User is on Central time.")


def test_stale_input_rejected_until_rebuilt(engine, story):
    engine.retract(story["globex"])
    with pytest.raises(RederiveError, match="stale"):
        engine.derive(["employer"], "Where they work.", "Works at Initech.", name="work_note")
    with pytest.raises(RederiveError, match="first"):
        engine.rebuild("profile", "User works at Initech.")


def test_newer_retraction_voids_old_job(engine, story):
    engine.retract(story["globex"])
    old_job = engine.store.one("SELECT * FROM rebuild_job WHERE state = 'queued' ORDER BY id")
    engine.retract(story["initech"])
    assert engine.store.one("SELECT state FROM rebuild_job WHERE id = ?", (old_job["id"],))["state"] == "discarded"
    # employer lost both inputs, so it is retracted with no rewrite needed.
    assert engine.recall(ref="employer")["memories"][0]["status"] == "retracted"


def test_derive_same_name_versions_and_invalidates(engine, story):
    out = engine.derive(["employer", "manager", "timezone"], "Short customer profile.",
                        "Works at Globex, reports to Priya, Central time.", name="profile")
    assert out["version"] == 2
    assert out["stale_count"] == 0  # nothing is built on the profile
    out = engine.derive([story["initech"], story["globex"]], "Where does the user work now?",
                        "User works at Globex (since March).", kind="belief", name="employer")
    assert out["version"] == 2
    assert sorted(names(out["rebuild_queue"])) == ["profile", "renewal_outreach"]


def test_cycle_rejected(engine, story):
    with pytest.raises(RederiveError, match="cycle"):
        engine.derive(["profile"], "Employer from profile.", "User works at Globex.", kind="belief",
                      name="employer")


def test_exposure_lists_recalls_of_changed_memory(engine, story):
    engine.recall("where does the user work")
    engine.recall(ref="timezone")
    assert engine.exposure() == []
    engine.retract(story["globex"])
    engine.rebuild("employer", "User works at Initech.")
    hits = engine.exposure()
    assert {h["memory"] for h in hits} >= {"employer"}
    assert "timezone" not in {h["memory"] for h in hits}
    employer = next(h for h in hits if h["memory"] == "employer")
    assert employer["state"] == "invalid"
    assert employer["latest_text"] == "User works at Initech."


def test_recall_ranks_and_scopes(engine):
    engine.remember("I prefer short replies with bullet points.", scope="global", name="style")
    engine.remember("The repo uses pnpm, not npm.")
    other = type(engine)(engine.store, project="/work/other")
    other.remember("Deploys go out on Fridays.")
    top = engine.recall("how should replies be formatted")["memories"][0]
    assert top["name"] == "style"
    texts = [m["text"] for m in engine.recall(limit=10)["memories"]]
    assert "Deploys go out on Fridays." not in texts
    assert "I prefer short replies with bullet points." in [m["text"] for m in other.recall()["memories"]]


def test_why_walks_to_observations(engine, story):
    tree = engine.why("profile")
    texts = {n["text"] for n in tree["nodes"].values()}
    assert "I work at Globex." in texts and "I am on Central time." in texts
    root = tree["nodes"][tree["root"]]
    assert root["instruction"].startswith("Short customer profile")


def test_correct_only_observations(engine, story):
    with pytest.raises(RederiveError, match="only remembered facts"):
        engine.correct("profile", "Something else.")


def test_persists_to_file(tmp_path):
    from rederive_local.engine import Engine
    from rederive_local.store import Store

    path = tmp_path / "m.db"
    e = Engine(Store(path), project="/p")
    a = e.remember("I work at Globex.")
    e.derive([a["id"]], "Employer.", "User works at Globex.", kind="belief", name="employer")
    e.retract(a["id"])
    e.store.close()
    e2 = Engine(Store(path), project="/p")
    assert names(e2.pending()) == []
    assert e2.recall(ref="employer")["memories"][0]["status"] == "retracted"
