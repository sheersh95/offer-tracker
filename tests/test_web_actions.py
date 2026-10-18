import json
import threading
import time

import pytest
from conftest import make_email, make_offer
from fastapi.testclient import TestClient

from offer_tracker.actions import Services
from offer_tracker.config import Settings
from offer_tracker.models import ExtractedOffer
from offer_tracker.store import OfferStore
from offer_tracker.web import create_app

CREDENTIALS = {"installed": {"client_id": "id", "client_secret": "secret"}}


class FakeGmail:
    def __init__(self, emails):
        self.emails = emails
        self.sent = []

    def search(self, query, limit):
        self.query = query
        return iter(self.emails[:limit])

    def send_html(self, to, subject, html):
        self.sent.append((to, subject, html))


class FakeExtractor:
    def extract(self, email):
        return [ExtractedOffer(store="Nike", title=f"Deal {email.id}", code=email.id.upper())]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFER_TRACKER_DATA_DIR", str(tmp_path))
    for var in ("ANTHROPIC_API_KEY", "DIGEST_TO"):
        monkeypatch.delenv(var, raising=False)
    gmail = FakeGmail([make_email(id="a"), make_email(id="b")])

    def authorize(settings):
        settings.token_path.write_text("{}")

    services = Services(
        gmail=lambda s: gmail, extractor=lambda s: FakeExtractor(), authorize=authorize
    )
    store = OfferStore(":memory:")
    app = create_app(offer_store=store, services=services)
    client = TestClient(app)
    client.gmail = gmail
    client.store = store
    client.data_dir = tmp_path
    return client


def wait_for_job(client, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get("/api/job").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_setup_flow_end_to_end(env):
    status = env.get("/api/status").json()
    assert not (status["credentials"] or status["gmail_connected"] or status["api_key"])

    # Buttons that need setup are refused with a clear message.
    assert env.post("/api/actions/sync", json={}).json()["detail"] == "Connect Gmail first"

    env.post("/api/settings", json={"credentials_json": json.dumps(CREDENTIALS)})
    assert env.post("/api/actions/connect-gmail", json={}).status_code == 200
    assert wait_for_job(env)["status"] == "succeeded"

    env.post("/api/settings", json={"anthropic_api_key": "sk-ant-test", "digest_to": "me@x.com"})
    status = env.get("/api/status").json()
    assert status == status | {
        "credentials": True,
        "gmail_connected": True,
        "api_key": True,
        "digest_to": "me@x.com",
    }

    assert env.post("/api/actions/sync", json={"days": 3, "limit": 10}).status_code == 200
    job = wait_for_job(env)
    assert job["status"] == "succeeded"
    assert "2 new offers" in job["message"]
    assert env.gmail.query == "category:promotions newer_than:3d"
    assert {o["code"] for o in env.get("/api/offers").json()} == {"A", "B"}

    env.post("/api/actions/send-digest", json={})
    job = wait_for_job(env)
    assert job["status"] == "succeeded", job
    [(to, subject, html)] = env.gmail.sent
    assert to == "me@x.com" and "2 new" in subject


def test_api_key_is_saved_locally_but_never_returned(env):
    env.post("/api/settings", json={"anthropic_api_key": "sk-ant-secret"})
    assert "sk-ant-secret" not in env.get("/api/status").text
    assert "sk-ant-secret" not in env.get("/").text
    assert Settings.from_env().anthropic_api_key == "sk-ant-secret"
    assert (env.data_dir / "settings.json").stat().st_mode & 0o077 == 0


def test_environment_variable_wins_over_saved_key(env, monkeypatch):
    env.post("/api/settings", json={"anthropic_api_key": "saved"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert Settings.from_env().anthropic_api_key == "from-env"


def test_rejects_files_that_are_not_oauth_clients(env):
    assert env.post("/api/settings", json={"credentials_json": "nope"}).status_code == 400
    assert env.post("/api/settings", json={"credentials_json": '{"a": 1}'}).status_code == 400
    assert not (env.data_dir / "credentials.json").exists()


def test_posts_must_be_json(env):
    # A plain form post (what another website could send) is refused.
    response = env.post("/api/actions/connect-gmail", data={"x": "1"})
    assert response.status_code == 415


def test_one_job_at_a_time(env):
    release = threading.Event()
    env.post("/api/settings", json={"credentials_json": json.dumps(CREDENTIALS)})
    (env.data_dir / "token.json").write_text("{}")
    env.post("/api/settings", json={"anthropic_api_key": "k"})

    class SlowGmail(FakeGmail):
        def search(self, query, limit):
            release.wait(5)
            return iter([])

    slow = SlowGmail([])
    app = create_app(
        offer_store=OfferStore(":memory:"),
        services=Services(gmail=lambda s: slow, extractor=lambda s: FakeExtractor()),
    )
    client = TestClient(app)
    assert client.post("/api/actions/sync", json={}).status_code == 200
    assert client.post("/api/actions/sync", json={}).status_code == 409
    release.set()
    assert wait_for_job(client)["status"] == "succeeded"


def test_digest_preview_page(env):
    env.store.upsert(make_offer())
    page = env.get("/digest")
    assert page.status_code == 200 and "FALL25" in page.text


def test_dashboard_shows_setup_until_ready(env):
    assert "Connect Gmail" in env.get("/").text
    assert "No offers yet" in env.get("/").text


def test_bad_api_key_stops_sync_with_a_clear_message(env):
    import anthropic
    import httpx

    class RejectingExtractor:
        calls = 0

        def extract(self, email):
            RejectingExtractor.calls += 1
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.AuthenticationError(
                "invalid x-api-key", response=httpx.Response(401, request=request), body=None
            )

    env.post("/api/settings", json={"credentials_json": json.dumps(CREDENTIALS)})
    (env.data_dir / "token.json").write_text("{}")
    env.post("/api/settings", json={"anthropic_api_key": "bad"})
    gmail = FakeGmail([make_email(id="a"), make_email(id="b")])
    client = TestClient(
        create_app(
            offer_store=OfferStore(":memory:"),
            services=Services(gmail=lambda s: gmail, extractor=lambda s: RejectingExtractor()),
        )
    )
    client.post("/api/actions/sync", json={})
    job = wait_for_job(client)
    assert job["status"] == "failed"
    assert job["message"] == "Claude rejected the API key. Paste a valid key in Setup."
    assert RejectingExtractor.calls == 1
