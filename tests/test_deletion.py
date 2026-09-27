import pytest

from rederive import RederiveError
from server.llm import FakeProvider
from server.verify import check
from server.workers.rebuild import drain
from tests.helpers import SUMMARY, extract

PHONE = extract("phone", r"(\+?\d[\d\s().-]{6,}\d)", "User's phone is {phone}.")


def build_contact(api):
    m1 = api.observe("My phone number is 512-555-0199.")
    m2 = api.observe("Call me at 512 555 0199 after 5pm.")
    m3 = api.observe("I prefer email.")
    contact = api.derive([m1, m2, m3], SUMMARY)
    phone = api.derive([contact], PHONE, kind="belief")
    return m1, m2, m3, contact, phone


def test_verifier_checks():
    c = [{"id": "c1", "payload": "512-555-0199"}]
    llm = FakeProvider()
    exact, = check("call 512-555-0199", c, llm)
    assert exact.exact_hit and exact.violated
    norm, = check("call (512) 555 0199", c, llm)
    assert not norm.exact_hit and norm.normalized_hit
    para, = check("Their number ends in 0199.", c, llm)
    assert not para.exact_hit and not para.normalized_hit and para.paraphrase_hit
    clean, = check("I prefer email.", c, llm)
    assert not clean.violated


def test_delete_rebuilds_without_deleted_content(api, run_jobs):
    m1, m2, m3, contact, phone = build_contact(api)
    out = api.delete(m1["id"])
    assert out["stale_count"] == 2 and len(out["constraint_ids"]) == 2
    run_jobs()

    text = api.read(contact["id"])["text"]
    # m2 repeats the number in another format. The verifier caught it and the
    # exclusion retry dropped it.
    assert "0199" not in text
    assert text == "I prefer email."
    assert api.read(phone["id"])["text"] == "User's phone is unknown."

    with pytest.raises(RederiveError) as err:
        api.read(m1["id"])
    assert err.value.status == 410
    assert api.lineage(contact["id"], 1)["nodes"][f"{m1['id']}@1"]["text"] == "[deleted]"

    report = api.deletion_report(m1["id"])
    attempts = {(c["record_id"], c["attempt"]): c for c in report["checks"]
                if c["record_id"] == contact["id"] and c["normalized_hit"]}
    assert (contact["id"], 1) in attempts
    final = [c for c in report["checks"] if c["record_id"] == contact["id"] and c["version"] == 2
             and c["attempt"] == 2]
    assert final and not any(c["exact_hit"] or c["normalized_hit"] or c["paraphrase_hit"] for c in final)
    # The second observation still holds the number. The report says so.
    assert {r["id"] for r in report["residual"]} == {m2["id"]}


class StubbornProvider(FakeProvider):
    """Ignores the exclusion instruction, like a model that leaks anyway."""

    def run_recipe(self, template, model, params, inputs, exclusions):
        return super().run_recipe(template, model, params, inputs, [])


def test_delete_fails_loudly_when_rebuild_still_leaks(api, pool):
    m1, m2, m3, contact, phone = build_contact(api)
    api.delete(m1["id"])
    counts = drain(pool, llm=StubbornProvider())
    assert counts["failed"] == 2  # contact fails the verifier, phone fails with its parent
    assert api.read(contact["id"])["status"] == "stale"
    jobs = api.jobs()["jobs"]
    reasons = {j["result"]["reason"] for j in jobs if j["state"] == "failed"}
    assert reasons == {"deletion_verifier", "parent_failed"}
    assert api.deletion_report(m1["id"])["failed_jobs"]
