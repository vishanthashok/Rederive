import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost:5432/rederive_test")
os.environ["REDERIVE_LLM"] = "fake"
os.environ["REDERIVE_EMBEDDER"] = "hashing"
os.environ["REDERIVE_ALLOW_RESET"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from rederive import Rederive  # noqa: E402
from server.app import app  # noqa: E402
from server.db.pool import apply_schema, get_pool, reset  # noqa: E402
from server.workers.rebuild import drain  # noqa: E402


@pytest.fixture(scope="session")
def pool():
    p = get_pool()
    apply_schema(p)
    return p


@pytest.fixture()
def api(pool):
    reset(pool)
    with TestClient(app) as http:
        # Tests run jobs with drain(), straight from Postgres.
        app.state.queue = None
        yield Rederive(http=http)


@pytest.fixture()
def run_jobs(pool):
    return lambda: drain(pool)
