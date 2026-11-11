"""Auto-detection of a local model server, and the config override."""
from __future__ import annotations

import asyncio
import json
import pytest

from app.config import get_settings
from app.services import llm


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from app.services import llm
    from app.config import get_settings
    
    llm._probe.update({"checked_at": 0.0, "base_url": "", "model": ""})
    get_settings.cache_clear()
    
    # Allow these specific tests to actually test local detection
    if hasattr(llm, "_original_detect_local"):
        monkeypatch.setattr(llm, "_detect_local", llm._original_detect_local)
    
    yield
    
    llm._probe.update({"checked_at": 0.0, "base_url": "", "model": ""})
    get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_nothing_running_means_not_available(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    assert llm.available() is False
    assert llm.describe()["connected"] is False


def test_local_ollama_is_detected_without_any_config(monkeypatch):
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse({"models": [{"name": "llama3.2:latest"}]}))
    assert llm.available() is True
    d = llm.describe()
    assert d["connected"] is True
    assert d["source"] == "detected local Ollama"
    assert d["model"] == "llama3.2:latest"
    base, model, key = llm.resolve()
    assert base == "http://localhost:11434/v1"


def test_a_small_instruct_model_is_preferred(monkeypatch):
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse({"models": [
                            {"name": "nomic-embed-text"}, {"name": "llama3.2:3b"}]}))
    assert llm.resolve()[1] == "llama3.2:3b"


def test_no_models_pulled_means_not_available(monkeypatch):
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse({"models": []}))
    assert llm.available() is False


def test_explicit_configuration_wins_over_detection(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse({"models": [{"name": "llama3.2"}]}))
    base, model, key = llm.resolve()
    assert base == "https://example.test/v1" and model == "configured-model" and key == "sk-test"
    assert llm.describe()["source"] == "configured"


def test_probe_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return _FakeResponse({"models": [{"name": "llama3.2"}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", counting)
    for _ in range(5):
        llm.available()
    assert calls["n"] == 1, "the probe must not run on every message"


def test_timeouts_allow_for_a_cold_model_load():
    """A local model loads ~2 GB on its first call. Short ceilings aborted every
    cold start and fell back to the corpus, which looked like 'not connected'."""
    import inspect
    from app.services import llm

    for fn in (llm.rephrase, llm.answer_open, llm.answer_clinical):
        default = inspect.signature(fn).parameters["timeout"].default
        assert default >= 60, f"{fn.__name__} timeout {default}s is too short for a cold load"


def test_requests_ask_the_provider_to_keep_the_model_resident(monkeypatch):
    """Only the first question should be slow."""
    from app.services import llm

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        is_closed = False

        async def post(self, url, json=None, headers=None, timeout=None):
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(llm, "resolve", lambda: ("http://x/v1", "m", "k"))
    monkeypatch.setattr(llm, "_get_client", lambda: _Client())

    asyncio.run(llm.answer_open("hello"))
    assert captured["body"].get("keep_alive") == "10m"


def test_a_provider_failure_falls_back_instead_of_raising(monkeypatch):
    """A provider outage must never reach the user in place of medical text."""
    import httpx
    from app.services import llm

    class _Client:
        is_closed = False

        async def post(self, *a, **k):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm, "resolve", lambda: ("http://x/v1", "m", "k"))
    monkeypatch.setattr(llm, "_get_client", lambda: _Client())
    assert asyncio.run(llm.answer_open("hello")) is None
    assert asyncio.run(llm.rephrase("q", "reference text")) is None


def test_warmup_reports_cleanly_with_no_model(monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "resolve", lambda: ("", "", ""))
    out = asyncio.run(llm.warm_up())
    assert out["warmed"] is False and "no model" in out["reason"]


def test_diagnose_gives_actionable_advice_when_nothing_is_detected(monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "resolve", lambda: ("", "", ""))
    out = asyncio.run(llm.diagnose())
    assert out["detected"] is False
    assert "ollama" in out["advice"].lower()


def test_diagnose_recommends_a_smaller_model_when_slow(monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "resolve", lambda: ("http://x/v1", "llama3.2", "k"))
    async def _ready(*a, **k):
        return "ready"
    monkeypatch.setattr(llm, "answer_open", _ready)
    monkeypatch.setattr(llm.time, "time", _clock([0.0, 40.0]))
    out = asyncio.run(llm.diagnose())
    assert out["responded"] is True
    assert "1b" in out["advice"]


def test_diagnose_flags_a_non_responding_model(monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "resolve", lambda: ("http://x/v1", "llama3.2", "k"))
    async def _none(*a, **k):
        return None
    monkeypatch.setattr(llm, "answer_open", _none)
    out = asyncio.run(llm.diagnose())
    assert out["responded"] is False
    assert "too large" in out["advice"]


def _clock(values):
    seq = list(values)

    def _t():
        return seq.pop(0) if seq else 999.0
    return _t


def test_warmup_endpoint_is_reachable(client):
    r = client.post("/api/v1/chat/warmup")
    assert r.status_code == 200
    assert "warmed" in r.json()


def test_diagnose_endpoint_is_reachable(client):
    r = client.get("/api/v1/chat/diagnose")
    assert r.status_code == 200
    assert "detected" in r.json()
