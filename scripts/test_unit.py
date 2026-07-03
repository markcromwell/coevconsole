import importlib
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect


def _load_app(monkeypatch, tmp_path, api_key=None):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    if api_key is None:
        monkeypatch.delenv("COUNCIL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("COUNCIL_API_KEY", api_key)

    import app.config as config
    import app.db as db
    import app.models as models
    import app.coev2_client as coev2_client
    import app.routers.bff as bff
    import app.routers.web as web
    import app as app_module

    config = importlib.reload(config)
    db = importlib.reload(db)
    models = importlib.reload(models)
    coev2_client = importlib.reload(coev2_client)
    bff = importlib.reload(bff)
    importlib.reload(web)
    app_module = importlib.reload(app_module)
    return app_module.create_app(), db, models, coev2_client, bff, config


class FakeCoEv2Client:
    def __init__(self, grade_result=None, job_result=None, error=None):
        self.grade_result = grade_result or {
            "job_id": "job-1",
            "status": "complete",
            "score": 0.91,
            "findings": ["actual finding"],
            "cost": "0.00",
        }
        self.job_result = job_result or {
            "job_id": "job-1",
            "status": "complete",
            "score": 0.97,
            "findings": ["live finding"],
        }
        self.error = error
        self.grade_calls = []
        self.poll_calls = []
        self.get_job_calls = []

    def grade(self, payload):
        self.grade_calls.append(payload)
        if self.error:
            raise self.error
        result = self.grade_result(payload) if callable(self.grade_result) else self.grade_result
        return result, "corr-grade"

    def get_job(self, job_id, kind):
        path = f"/{kind}/{job_id}"
        self.poll_calls.append((job_id, kind))
        self.get_job_calls.append({"job_id": job_id, "kind": kind, "path": path})
        if self.error:
            raise self.error
        result = self.job_result((job_id, kind)) if callable(self.job_result) else self.job_result
        return result, "corr-live"


def _override_client(app, coev2_client_module, fake):
    app.dependency_overrides[coev2_client_module.get_coev2_client] = lambda: fake


def _hidden(html, name):
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    assert match, html
    return match.group(1)


GRADE_FORM = {"program_id": 42, "level": "story", "content": "operator input"}
GRADE_REQUEST = {
    "program_id": 42,
    "level": "story",
    "artifact": {"content": "operator input"},
}


def test_health_root_model_and_config_ok(monkeypatch, tmp_path):
    app, db, models, _, _, config = _load_app(monkeypatch, tmp_path, api_key="server-secret")
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200
    assert config.settings.council_api_key == "server-secret"
    assert config.settings.coev2_api_base_url
    assert "submissions" in inspect(db.engine).get_table_names()
    assert list(models.Submission.__table__.columns.keys()) == [
        "console_id",
        "coev2_job_id",
        "kind",
        "submitted_at",
        "last_seen_status",
        "last_seen_score",
        "idempotency_key",
    ]


def test_key_attached_upstream_but_redacted_from_logs_and_responses(monkeypatch, tmp_path, caplog):
    app, _, _, coev2_client, _, config = _load_app(monkeypatch, tmp_path, api_key="super-secret")
    seen = {}

    class FakeHTTPXClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, url, headers=None, **kwargs):
            seen["headers"] = headers
            return httpx.Response(
                200,
                json={
                    "job_id": "job-redacted",
                    "score": 1,
                    "findings": ["super-secret must not leak"],
                },
            )

    monkeypatch.setattr(coev2_client.httpx, "Client", FakeHTTPXClient)
    caplog.set_level("INFO")
    client = TestClient(app)

    draft = client.post("/bff/grade/prepare", json={"payload": GRADE_FORM}).json()
    response = client.post("/bff/grade/confirm", json=draft)

    assert seen["headers"]["Authorization"] == "Bearer super-secret"
    assert "super-secret" not in response.text
    assert "super-secret" not in client.get("/").text
    assert "super-secret" not in client.get("/health").text
    assert "super-secret" not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert config.settings.council_api_key == "super-secret"


def test_confirm_grade_sends_valid_grade_request_and_renders_score(monkeypatch, tmp_path):
    app, db, _, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    fake = FakeCoEv2Client(grade_result={"job_id": "job-grade", "status": "complete", "score": 0.72})
    _override_client(app, coev2_client, fake)
    client = TestClient(app)

    draft = client.post("/bff/grade/prepare", json={"payload": GRADE_FORM}).json()
    response = client.post("/bff/grade/confirm", json=draft).json()

    assert fake.grade_calls == [GRADE_REQUEST]
    assert "prompt" not in fake.grade_calls[0]
    assert response["result"]["score"] == 0.72

    with db.SessionLocal() as session:
        rows = session.execute(db.Base.metadata.tables["submissions"].select()).all()
    assert len(rows) == 1
    assert rows[0]._mapping["last_seen_score"] == 0.72


def test_confirm_is_idempotent_and_resubmit_is_fresh(monkeypatch, tmp_path):
    app, db, _, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    fake = FakeCoEv2Client(grade_result={"job_id": "job-one", "status": "queued", "score": 0.4})
    _override_client(app, coev2_client, fake)
    client = TestClient(app)

    payload = {"program_id": 7, "level": "epic", "content": "one"}
    draft = client.post("/bff/grade/prepare", json={"payload": payload}).json()
    assert fake.grade_calls == []

    first = client.post("/bff/grade/confirm", json=draft).json()
    second = client.post("/bff/grade/confirm", json=draft).json()
    assert first["coev2_job_id"] == "job-one"
    assert second["duplicate"] is True
    assert second["coev2_job_id"] == "job-one"
    assert fake.grade_calls == [
        {"program_id": 7, "level": "epic", "artifact": {"content": "one"}}
    ]
    assert "prompt" not in fake.grade_calls[0]

    with db.SessionLocal() as session:
        rows = session.execute(db.Base.metadata.tables["submissions"].select()).all()
    assert len(rows) == 1
    assert rows[0]._mapping["kind"] == "grade"
    assert rows[0]._mapping["coev2_job_id"] == "job-one"
    assert rows[0]._mapping["submitted_at"] is not None

    resubmit = client.post("/bff/grade/prepare", json={"payload": payload}).json()
    assert resubmit["idempotency_key"] != draft["idempotency_key"]
    assert resubmit["confirm_token"] != draft["confirm_token"]


def test_submit_and_render_uses_actual_json_and_cost_honesty(monkeypatch, tmp_path):
    app, _, _, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)

    def grade_result(payload):
        content = payload["artifact"]["content"]
        return {
            "job_id": "job-dynamic",
            "status": "complete",
            "nested": {
                "score": 0.33 if content == "low" else 0.88,
                "findings": [f"finding for {content}"],
                "cost": "$0.01",
            },
        }

    fake = FakeCoEv2Client(grade_result=grade_result)
    _override_client(app, coev2_client, fake)
    client = TestClient(app)

    prepare = client.post(
        "/grade/prepare",
        data={"program_id": 99, "level": "spec", "content": "high"},
    )
    assert "Confirm spend" in prepare.text
    assert "Backend reported cost: unknown" in prepare.text
    assert "may spend backend resources" in prepare.text

    confirm = client.post(
        "/grade/confirm",
        data={
            "confirm_token": _hidden(prepare.text, "confirm_token"),
            "idempotency_key": _hidden(prepare.text, "idempotency_key"),
        },
    )
    assert "Score: 0.88" in confirm.text
    assert "finding for high" in confirm.text
    assert "Cost: $0.01" in confirm.text
    assert "0.33" not in confirm.text


def test_history_lists_last_20_and_submission_page_polls_live(monkeypatch, tmp_path):
    app, db, models, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    fake = FakeCoEv2Client(
        job_result={"job_id": "job-24", "status": "complete", "score": 99, "findings": ["fresh"]}
    )
    _override_client(app, coev2_client, fake)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with db.SessionLocal() as session:
        for index in range(25):
            session.add(
                models.Submission(
                    console_id=f"console-{index}",
                    coev2_job_id=f"job-{index}",
                    kind="grade",
                    submitted_at=base_time + timedelta(minutes=index),
                    last_seen_status="stale",
                    last_seen_score=1,
                    idempotency_key=f"idem-{index}",
                )
            )
        session.commit()

    client = TestClient(app)
    history = client.get("/bff/submissions").json()
    assert len(history) == 20
    assert history[0]["console_id"] == "console-24"
    assert history[-1]["console_id"] == "console-5"

    page = client.get("/submissions/console-24")
    assert "Score: 99" in page.text
    assert "fresh" in page.text
    assert fake.poll_calls == [("job-24", "grade")]
    assert fake.get_job_calls == [
        {"job_id": "job-24", "kind": "grade", "path": "/grade/job-24"}
    ]


def test_bff_submission_polls_kind_scoped_path_and_surfaces_live_score(monkeypatch, tmp_path):
    app, db, models, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    fake = FakeCoEv2Client(
        job_result={
            "id": "job-live",
            "status": "complete",
            "score": 0.84,
            "actual_cost_usd": 0.12,
        }
    )
    _override_client(app, coev2_client, fake)
    with db.SessionLocal() as session:
        session.add(
            models.Submission(
                console_id="console-live",
                coev2_job_id="job-live",
                kind="grade",
                submitted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-live",
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.get("/bff/submissions/console-live").json()

    assert fake.get_job_calls == [
        {"job_id": "job-live", "kind": "grade", "path": "/grade/job-live"}
    ]
    assert fake.get_job_calls[0]["path"] != "/jobs/job-live"
    assert response["live"]["status"] == "complete"
    assert response["live"]["score"] == 0.84
    assert response["live"]["actual_cost_usd"] == 0.12


def test_submission_page_renders_live_poll_not_stale_last_seen(monkeypatch, tmp_path):
    app, db, models, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    fake = FakeCoEv2Client(
        job_result={
            "id": "job-stale",
            "status": "complete",
            "score": 0.67,
            "actual_cost_usd": 0.05,
            "findings": ["polled live"],
        }
    )
    _override_client(app, coev2_client, fake)
    with db.SessionLocal() as session:
        session.add(
            models.Submission(
                console_id="console-stale",
                coev2_job_id="job-stale",
                kind="grade",
                submitted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-stale",
            )
        )
        session.commit()

    client = TestClient(app)
    page = client.get("/submissions/console-stale")

    assert "Status: complete" in page.text
    assert "Score: 0.67" in page.text
    assert "Cost: 0.05" in page.text
    assert "polled live" in page.text
    assert page.text.index("Status: complete") < page.text.index("History")
    assert fake.get_job_calls == [
        {"job_id": "job-stale", "kind": "grade", "path": "/grade/job-stale"}
    ]


def test_index_live_polls_non_terminal_history_and_persists_refresh(monkeypatch, tmp_path):
    app, db, models, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)

    def job_result(call):
        job_id, _ = call
        return {"id": job_id, "status": "complete", "score": 0.64}

    fake = FakeCoEv2Client(job_result=job_result)
    _override_client(app, coev2_client, fake)
    base_time = datetime(2026, 1, 5, tzinfo=timezone.utc)
    with db.SessionLocal() as session:
        session.add(
            models.Submission(
                console_id="console-old",
                coev2_job_id="job-old",
                kind="grade",
                submitted_at=base_time,
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-old",
            )
        )
        for index in range(19):
            session.add(
                models.Submission(
                    console_id=f"console-terminal-{index}",
                    coev2_job_id=f"job-terminal-{index}",
                    kind="grade",
                    submitted_at=base_time + timedelta(minutes=index + 1),
                    last_seen_status="complete",
                    last_seen_score=1,
                    idempotency_key=f"idem-terminal-{index}",
                )
            )
        session.add(
            models.Submission(
                console_id="console-live-list",
                coev2_job_id="job-live-list",
                kind="grade",
                submitted_at=base_time + timedelta(minutes=20),
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-live-list",
            )
        )
        session.add(
            models.Submission(
                console_id="console-terminal-recent",
                coev2_job_id="job-terminal-recent",
                kind="grade",
                submitted_at=base_time + timedelta(minutes=21),
                last_seen_status="completed",
                last_seen_score=0.9,
                idempotency_key="idem-terminal-recent",
            )
        )
        session.commit()

    client = TestClient(app)
    page = client.get("/")

    assert page.status_code == 200
    assert re.search(r"complete\s*/\s*0\.64", page.text)
    assert not re.search(r"running\s*/\s*unknown", page.text)
    assert fake.poll_calls == [("job-live-list", "grade")]
    assert ("job-terminal-recent", "grade") not in fake.poll_calls
    assert ("job-old", "grade") not in fake.poll_calls

    with db.SessionLocal() as session:
        refreshed = session.get(models.Submission, "console-live-list")
        terminal = session.get(models.Submission, "console-terminal-recent")
    assert refreshed.last_seen_status == "complete"
    assert refreshed.last_seen_score == 0.64
    assert terminal.last_seen_status == "completed"
    assert terminal.last_seen_score == 0.9


def test_index_failed_live_poll_marks_only_that_history_row_stale(monkeypatch, tmp_path):
    app, db, models, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    from app.coev2_client import CoEv2ClientError

    def job_result(call):
        job_id, _ = call
        if job_id == "job-fail-list":
            raise CoEv2ClientError("CoEv2 request timed out", "corr-stale-list", 504)
        return {"id": job_id, "status": "complete", "score": 0.73}

    fake = FakeCoEv2Client(job_result=job_result)
    _override_client(app, coev2_client, fake)
    base_time = datetime(2026, 1, 6, tzinfo=timezone.utc)
    with db.SessionLocal() as session:
        session.add(
            models.Submission(
                console_id="console-fail-list",
                coev2_job_id="job-fail-list",
                kind="grade",
                submitted_at=base_time,
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-fail-list",
            )
        )
        session.add(
            models.Submission(
                console_id="console-ok-list",
                coev2_job_id="job-ok-list",
                kind="grade",
                submitted_at=base_time + timedelta(minutes=1),
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-ok-list",
            )
        )
        session.add(
            models.Submission(
                console_id="console-terminal-list",
                coev2_job_id="job-terminal-list",
                kind="grade",
                submitted_at=base_time + timedelta(minutes=2),
                last_seen_status="failed",
                last_seen_score=None,
                idempotency_key="idem-terminal-list",
            )
        )
        session.commit()

    client = TestClient(app)
    page = client.get("/")

    assert page.status_code == 200
    assert re.search(r"running\s*/\s*unknown", page.text)
    assert "stale (Correlation ID: corr-stale-list)" in page.text
    assert re.search(r"complete\s*/\s*0\.73", page.text)
    assert fake.poll_calls == [("job-ok-list", "grade"), ("job-fail-list", "grade")]
    assert ("job-terminal-list", "grade") not in fake.poll_calls


def test_unknown_kind_poll_fails_cleanly_with_correlation_id(monkeypatch, tmp_path):
    app, db, models, _, _, _ = _load_app(monkeypatch, tmp_path)
    with db.SessionLocal() as session:
        session.add(
            models.Submission(
                console_id="console-bad-kind",
                coev2_job_id="job-bad",
                kind="unknown-kind",
                submitted_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
                last_seen_status="running",
                last_seen_score=None,
                idempotency_key="idem-bad",
            )
        )
        session.commit()

    client = TestClient(app)
    bff_response = client.get("/bff/submissions/console-bad-kind").json()
    page = client.get("/submissions/console-bad-kind")

    assert "error" in bff_response
    assert "Unsupported job kind" in bff_response["error"]
    assert bff_response["correlation_id"]
    assert "Backend error" in page.text
    assert "Unsupported job kind" in page.text
    assert re.search(r"Correlation ID: [0-9a-f-]{36}", page.text)


def test_failure_empty_loading_and_malformed_states_render_safely(monkeypatch, tmp_path):
    app, _, _, coev2_client, _, _ = _load_app(monkeypatch, tmp_path)
    client = TestClient(app)
    assert "No submissions yet." in client.get("/").text
    assert "Loading" in client.get("/loading").text

    malformed = FakeCoEv2Client(grade_result=["not", "an", "object"])
    _override_client(app, coev2_client, malformed)
    draft = client.post(
        "/grade/prepare",
        data={"program_id": 1, "level": "vision", "content": "bad"},
    )
    response = client.post(
        "/grade/confirm",
        data={
            "confirm_token": _hidden(draft.text, "confirm_token"),
            "idempotency_key": _hidden(draft.text, "idempotency_key"),
        },
    )
    assert "Malformed response received" in response.text

    from app.coev2_client import CoEv2ClientError

    failing = FakeCoEv2Client(error=CoEv2ClientError("CoEv2 backend error", "corr-500", 502))
    _override_client(app, coev2_client, failing)
    draft = client.post(
        "/grade/prepare",
        data={"program_id": 1, "level": "vision", "content": "fail"},
    )
    response = client.post(
        "/grade/confirm",
        data={
            "confirm_token": _hidden(draft.text, "confirm_token"),
            "idempotency_key": _hidden(draft.text, "idempotency_key"),
        },
    )
    assert "Backend error" in response.text
    assert "corr-500" in response.text
