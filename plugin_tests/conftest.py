import pytest

import plugin_paths  # noqa: F401  (puts the plugin's server folder on sys.path)
from rederive_local.engine import Engine
from rederive_local.store import Store


@pytest.fixture()
def engine():
    store = Store(":memory:")
    yield Engine(store, project="/work/acme")
    store.close()


@pytest.fixture()
def story(engine):
    """The demo's wrong-employer story: two employer facts, a belief, a profile."""
    e = engine
    ids = {
        "initech": e.remember("I started working at Initech in March.", topic="work")["id"],
        "globex": e.remember("I work at Globex.", topic="work")["id"],
        "manager": e.remember("My manager is Priya.", topic="work")["id"],
        "tz": e.remember("I am on Central time.", topic="work")["id"],
        "phone": e.remember("My phone is 512-555-0199.", topic="contact")["id"],
    }
    e.derive([ids["initech"], ids["globex"]], "Where does the user work now? Use the most recent statement.",
             "User works at Globex.", kind="belief", name="employer")
    e.derive([ids["manager"]], "Who is the user's manager?", "User's manager is Priya.",
             kind="belief", name="manager")
    e.derive([ids["tz"]], "What time zone is the user in?", "User is on Central time.",
             kind="belief", name="timezone")
    e.derive(["employer", "manager", "timezone"], "Short customer profile, one sentence per fact.",
             "User works at Globex. User's manager is Priya. User is on Central time.", name="profile")
    e.derive(["employer", "manager"], "Renewal outreach plan.",
             "Before renewal, contact Priya at Globex.", kind="procedure", name="renewal_outreach")
    e.derive([ids["phone"], ids["tz"]], "How to contact the user.",
             "Text 512-555-0199 during Central business hours.", kind="procedure", name="contact_plan")
    return ids
