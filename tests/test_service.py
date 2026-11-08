"""API tests for service/app.py with a fake model (no weights, no object storage)."""
import pytest
from fastapi.testclient import TestClient

import app as service


class FakeParser:
    def __init__(self, reply):
        self.reply = reply

    def generate(self, text, max_new_tokens=64):
        return self.reply


GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MODEL_VERSION", "v9")
    monkeypatch.setenv("FAULT_INJECT", "0")
    service.state.parser = None
    service.state.error = None
    yield TestClient(service.app)          # not used as a context manager: no background download
    service.state.parser = None


def test_health_and_readiness(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503          # model not loaded yet
    service.state.parser = FakeParser(GOOD)
    assert client.get("/readyz").status_code == 200


def test_parse_returns_exact_object_and_headers(client):
    service.state.parser = FakeParser(GOOD)
    r = client.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 200
    assert r.json() == {"intent": "weather_query", "date": None, "time": None, "place": "london"}
    assert list(r.json().keys()) == ["intent", "date", "time", "place"]
    assert r.headers["X-Model-Version"] == "v9"
    assert r.headers["X-Served-By"]


def test_fault_inject_returns_500(client, monkeypatch):
    service.state.parser = FakeParser(GOOD)
    monkeypatch.setenv("FAULT_INJECT", "1")
    r = client.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 500 and r.json() == {"error": "invalid_model_output"}


@pytest.mark.parametrize("bad", [
    "not json",
    '{"intent": "weather_query", "date": null, "time": null}',                         # missing key
    '{"intent": "play_music", "date": null, "time": null, "place": null}',             # unknown intent
    '{"intent": "weather_query", "date": 5, "time": null, "place": null}',             # wrong type
    '{"intent": "weather_query", "date": null, "time": null, "place": null, "x": 1}',  # extra key
])
def test_invalid_model_output_is_never_returned_as_200(client, bad):
    service.state.parser = FakeParser(bad)
    r = client.post("/parse", json={"text": "anything"})
    assert r.status_code == 500 and r.json() == {"error": "invalid_model_output"}


def test_parse_before_ready_is_503(client):
    assert client.post("/parse", json={"text": "hello"}).status_code == 503
