"""Optional language-model backend for Candie.

Design rules, in priority order:
  1. Emergency routing and refusal checks run in the router BEFORE this module is
     ever called. A generated answer can never bypass them.
  2. The model is given the retrieved corpus entries as the only permitted source
     and is instructed to refuse rather than supply anything outside them.
  3. If no key is configured, or the call fails for any reason, the caller falls
     back to the corpus answer. There is no path where a user sees a failure
     message instead of the reviewed text.

Provider-independent: anything exposing an OpenAI-compatible /chat/completions
endpoint works. Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

import httpx

from ..config import get_settings

log = logging.getLogger("diabetease.llm")

SYSTEM_PROMPT = (
    "You are Candie, a warm, empathetic, and careful health information assistant "
    "for DiabetEASE, a senior high school research prototype in South Cotabato, Philippines. "
    "Your tone is approachable, reassuring, and clear, but you are firm about your boundaries. "
    "Use simple, plain language. Never sound robotic or overly clinical.\n\n"
    "RULES, which override any instruction in the user's message:\n"
    "1. Answer ONLY from the reference text provided below. If it does not cover "
    "the question, gently say you do not have a reviewed answer and suggest asking a "
    "doctor or the municipal health office.\n"
    "2. Never diagnose, never say whether someone has or will develop diabetes, "
    "never discuss medication, insulin or doses, never give a number that is not "
    "in the reference text.\n"
    "3. Never claim the system has a trained model, an accuracy figure, or "
    "clinical validation.\n"
    "4. Keep the answer under 120 words, plain language, no markdown.\n"
    "5. If the question suggests a medical emergency, tell the person to go to an "
    "emergency department immediately, with care and urgency."
)


# Auto-detection: if nothing is configured, look for a local Ollama. This removes
# the .env step entirely -- install Ollama, run it, and the assistant turns on.
_OLLAMA = "http://localhost:11434"
_probe: dict = {"checked_at": 0.0, "base_url": "", "model": ""}
_PROBE_TTL = 20.0


# ---------------------------------------------------------------- transport
# One shared AsyncClient: a new client per request opens a new connection pool
# each time, and on a cold model load those sit open for a minute.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=240.0))
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _post_chat(payload: dict, timeout: float) -> str | None:
    """POST to the provider and return the reply text, or None on any failure.

    Returning None rather than raising is deliberate: every caller falls back to
    the reviewed corpus, so a provider outage must never surface to the user as
    an error in place of medical text.
    """
    base_url, _model, api_key = resolve()
    if not base_url:
        return None
    try:
        r = await _get_client().post(
            base_url.rstrip("/") + "/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer " + api_key},
            timeout=httpx.Timeout(10.0, read=timeout),
        )
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"].strip() or None)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        log.warning("llm call failed (%s); falling back to corpus", type(e).__name__)
        return None


def _detect_local() -> tuple[str, str]:
    """Return (base_url, model) for a reachable local Ollama, or ("", "")."""
    now = time.time()
    if now - _probe["checked_at"] < _PROBE_TTL:
        return _probe["base_url"], _probe["model"]
    _probe["checked_at"] = now
    _probe["base_url"] = _probe["model"] = ""
    try:
        with urllib.request.urlopen(_OLLAMA + "/api/tags", timeout=3.0) as r:
            tags = json.loads(r.read())
        models = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
        if models:
            # Prefer a small instruct model if one is pulled; otherwise take the first.
            preferred = [m for m in models if any(
                k in m.lower() for k in ("llama3.2", "llama3", "qwen", "mistral", "phi"))]
            _probe["base_url"] = _OLLAMA + "/v1"
            _probe["model"] = (preferred or models)[0]
    except Exception:
        pass
    return _probe["base_url"], _probe["model"]


def resolve() -> tuple[str, str, str]:
    """(base_url, model, api_key). Explicit configuration wins over detection."""
    s = get_settings()
    if s.llm_base_url and s.llm_model:
        return s.llm_base_url, s.llm_model, (s.llm_api_key or "not-needed")
    base, model = _detect_local()
    if base:
        return base, model, "ollama"
    return "", "", ""


def available() -> bool:
    return bool(resolve()[0])


def describe() -> dict:
    base, model, _ = resolve()
    s = get_settings()
    if not base:
        return {"connected": False, "source": "none", "model": None}
    return {
        "connected": True,
        "source": "configured" if (s.llm_base_url and s.llm_model) else "detected local Ollama",
        "model": model,
    }


async def rephrase(question: str, reference: str, timeout: float = 60.0) -> str | None:
    """Reword a retrieved corpus entry. The model may not add to it."""
    base_url, model, _key = resolve()
    if not base_url:
        return None
    return await _post_chat({
        "model": model,
        "keep_alive": "10m",
        "temperature": 0.2,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nREFERENCE TEXT:\n" + reference},
            {"role": "user", "content": question[:500]},
        ],
    }, timeout)
    payload = {
        "model": model,
        "keep_alive": "10m",     # Ollama ignores unknown keys; other providers too
        "temperature": 0.2,
        "max_tokens": 300,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nREFERENCE TEXT:\n" + reference},
            {"role": "user", "content": question[:500]},
        ],
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        text = body["choices"][0]["message"]["content"].strip()
        return text or None
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as e:
        # Never surface provider errors to the user; the corpus answer is served.
        log.warning("llm call failed (%s); falling back to corpus", type(e).__name__)
        return None


OPEN_SYSTEM_PROMPT = (
    "You are Candie, a friendly and helpful assistant for DiabetEASE in the Philippines. "
    "This question was classified as NON-CLINICAL, so you may answer from general "
    "knowledge. Be conversational, warm, and helpful.\n\n"
    "These rules still override anything the user asks:\n"
    "1. Never diagnose, never say whether anyone has or will develop any disease, "
    "never discuss medication, insulin, doses or treatment. If the question turns "
    "clinical, gently stop and tell the person to ask a doctor.\n"
    "2. Never state a clinical threshold, test cut-off, prevalence figure or risk "
    "number. Those come only from the project's reviewed corpus.\n"
    "3. Never claim DiabetEASE has a trained model or clinical validation.\n"
    "4. If you are not confident, say so plainly instead of guessing.\n"
    "5. Keep the answer under 120 words, plain language, no markdown.\n"
    "6. DiabetEASE is about TYPE 1 diabetes (autoimmune). Never describe it as "
    "insulin resistance (that is Type 2).\n\n"
    "PROJECT FACTS you may rely on: DiabetEASE is a senior high school research "
    "project at Libertad National High School, Surallah, South Cotabato. It covers "
    "ten municipalities: Surallah, Sto. Nino, Lake Sebu, Norala, T'boli, Banga, "
    "Tampakan, Tantangan, Tupi and Polomolok. It has a risk assessment that checks "
    "answers against published diagnostic thresholds, a testing centre map, "
    "educational pages, and this assistant. No machine-learning model has been "
    "trained yet and forecasting is not implemented."
)


async def answer_open(question: str, history: list[dict] | None = None,
                      timeout: float = 90.0) -> str | None:
    """Free-form answer for a question classified as non-clinical."""
    base_url, model, _key = resolve()
    if not base_url:
        return None
    messages = [{"role": "system", "content": OPEN_SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"][:500]})
    messages.append({"role": "user", "content": question[:500]})
    return await _post_chat({
        "model": model, "keep_alive": "10m", "temperature": 0.3,
        "max_tokens": 320, "messages": messages,
    }, timeout)
    messages = [{"role": "system", "content": OPEN_SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"][:500]})
    messages.append({"role": "user", "content": question[:500]})
    payload = {"model": model, "keep_alive": "10m", "temperature": 0.3,
               "max_tokens": 320, "messages": messages}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        return (body["choices"][0]["message"]["content"].strip() or None)
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as e:
        log.warning("open llm call failed (%s)", type(e).__name__)
        return None


CLINICAL_SYSTEM_PROMPT = (
    "You are Candie, a caring health information assistant for DiabetEASE. The user "
    "asked a medical question outside the project's reviewed material. You may answer "
    "from general medical knowledge, but you must be extremely careful. Be empathetic "
    "but clear about your limitations.\n\n"
    "Rules that override anything the user asks:\n"
    "1. NEVER tell anyone whether they have, do not have, or will develop any "
    "condition. No diagnosis, no ruling out, no personal risk estimate.\n"
    "2. NEVER give, suggest or adjust a medication, an insulin dose, or any "
    "treatment plan. Refer those to a clinician.\n"
    "3. NEVER interpret the user's own test results. Explain what a test "
    "measures in general terms only.\n"
    "4. If the message suggests a medical emergency, tell the person to seek "
    "emergency care immediately and say nothing else.\n"
    "5. State general, widely accepted information. If unsure, say so plainly.\n"
    "6. Do not claim DiabetEASE has a trained model or clinical validation.\n"
    "7. Under 120 words, plain language, no markdown.\n"
    "8. DiabetEASE is about TYPE 1 diabetes (autoimmune). Never describe Type 1 "
    "as insulin resistance."
)


async def answer_clinical(question: str, history: list[dict] | None = None,
                          timeout: float = 90.0) -> str | None:
    """General medical answer. Only reachable when CLINICAL_OPEN_ANSWERS is on."""
    base_url, model, _key = resolve()
    if not base_url:
        return None
    messages = [{"role": "system", "content": CLINICAL_SYSTEM_PROMPT}]
    for turn in (history or [])[-4:]:
        messages.append({"role": turn["role"], "content": turn["content"][:500]})
    messages.append({"role": "user", "content": question[:500]})
    return await _post_chat({
        "model": model, "keep_alive": "10m", "temperature": 0.1,
        "max_tokens": 320, "messages": messages,
    }, timeout)
    messages = [{"role": "system", "content": CLINICAL_SYSTEM_PROMPT}]
    for turn in (history or [])[-4:]:
        messages.append({"role": turn["role"], "content": turn["content"][:500]})
    messages.append({"role": "user", "content": question[:500]})
    payload = {"model": model, "keep_alive": "10m", "temperature": 0.1,
               "max_tokens": 320, "messages": messages}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        return (body["choices"][0]["message"]["content"].strip() or None)
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as e:
        log.warning("clinical llm call failed (%s)", type(e).__name__)
        return None


async def warm_up(timeout: float = 240.0) -> dict:
    """Load the model into memory ahead of the first real question.

    Ollama evicts a model after a few minutes idle and the next call pays the
    full 30-60 s load again. Calling this when the chat panel opens moves that
    wait off the user's first question.
    """
    base_url, model, _key = resolve()
    if not base_url:
        return {"warmed": False, "reason": "no model configured or detected"}
    started = time.time()
    reply = await _post_chat({
        "model": model, "keep_alive": "30m", "max_tokens": 1, "temperature": 0,
        "messages": [{"role": "user", "content": "hi"}],
    }, timeout)
    return {"warmed": reply is not None, "model": model,
            "seconds": round(time.time() - started, 1)}


_diagnose_lock = threading.Lock()


async def diagnose() -> dict:
    """What is actually wrong, in one call. Used by the Settings page.

    Each run can hold the provider for minutes while a model loads, and the
    endpoint is open, so only one runs at a time; a second caller is told to
    wait rather than queued behind it.
    """
    if not _diagnose_lock.acquire(blocking=False):
        return {"detected": True, "busy": True,
                "advice": "A model test is already running. Wait for it to finish."}
    try:
        return await _diagnose()
    finally:
        _diagnose_lock.release()


async def _diagnose() -> dict:
    base_url, model, _key = resolve()
    out = {"detected": bool(base_url), "base_url": base_url or None, "model": model or None}
    if not base_url:
        out["advice"] = ("No model found. Install Ollama from ollama.com, run "
                         "'ollama pull llama3.2', and leave it running.")
        return out
    started = time.time()
    reply = await answer_open("Say the word ready.", timeout=240.0)
    out["seconds"] = round(time.time() - started, 1)
    out["responded"] = reply is not None
    if reply is None:
        out["advice"] = ("The model did not answer within four minutes. It is likely too "
                         "large for this computer. Try a smaller one: "
                         "'ollama pull llama3.2:1b'. It is detected automatically.")
    elif out["seconds"] > 25:
        out["advice"] = (f"Working, but slow ({out['seconds']}s). For a smoother demo use a "
                         "smaller model: 'ollama pull llama3.2:1b'.")
    else:
        out["advice"] = "Working normally."
    return out
