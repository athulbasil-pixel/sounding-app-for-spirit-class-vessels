"""Test fixtures. All data is synthetic; each test gets its own temporary database."""
import pytest

from watchlog import create_app
from watchlog.db import connect
from watchlog.registry import load_registry


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, testing=True)


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "test-token"
    return c


@pytest.fixture
def conn(app):
    c = connect(app.config["DATABASE"])
    yield c
    c.close()


@pytest.fixture
def reg():
    return load_registry()


class Api:
    """Small helper that drives the app the way the browser does."""

    def __init__(self, client):
        self.c = client

    def start(self, d, w):
        r = self.c.post(f"/watch/{d}/{w}/start", data={"csrf": "test-token"})
        assert r.status_code == 302
        return r

    def put(self, d, w, field, raw, slot="watch", status="entered", reason=None):
        r = self.c.put(f"/api/watch/{d}/{w}/reading", json={"field": field, "slot": slot, "raw": raw,
                                                          "status": status, "reason": reason},
                       headers={"X-Watchlog": "1"})
        return r

    def state(self, d, w):
        r = self.c.get(f"/api/watch/{d}/{w}")
        assert r.status_code == 200
        return r.get_json()

    def item(self, d, w, field, slot="watch"):
        st = self.state(d, w)
        return next(i for i in st["items"] if i["field"] == field and i["slot"] == slot)

    def event(self, d, w, field, kind, series="6h", point=None, value=None, method="POST"):
        return self.c.open(f"/api/watch/{d}/{w}/event", method=method,
                           json={"field": field, "series": series, "point": point or w, "kind": kind, "value": value},
                           headers={"X-Watchlog": "1"})

    def settings(self, **form):
        return self.c.post("/settings", data={"csrf": "test-token", **form})


@pytest.fixture
def api(client):
    return Api(client)
