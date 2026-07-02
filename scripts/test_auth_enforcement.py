"""Auth-ENFORCEMENT test (+db) — proves require_api_key actually rejects, not merely that it's wired.

Catches the silent-no-op class (CoEv2 2026-06-21): an auth dependency that is present but reads the wrong
env var (so auth is bypassed in the deployed container) returns 201/200 here instead of 401. Auth rejects
BEFORE the DB is touched, so this is DB-independent. The golden ci.yml runs the whole scripts/ dir, so
this gate executes at merge — a feature router that drops/breaks auth fails CI. Mirror this for every new
authenticated router."""
import os

from fastapi.testclient import TestClient


def _app():
    os.environ["APP_API_KEY"] = "enforce-test-key"   # enforcement ON
    from main import app
    return app


def test_mutating_endpoint_401_without_key():
    with TestClient(_app()) as c:
        r = c.post("/items", json={"name": "x"})
    assert r.status_code == 401, f"POST /items without X-API-Key must be 401 — auth is NOT enforcing (got {r.status_code})"


def test_mutating_endpoint_401_with_wrong_key():
    with TestClient(_app()) as c:
        r = c.post("/items", json={"name": "x"}, headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401, f"wrong X-API-Key must be 401 (got {r.status_code})"
