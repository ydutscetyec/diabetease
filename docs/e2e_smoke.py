"""End-to-end smoke test against a running server. Run: python docs/e2e_smoke.py"""
from __future__ import annotations
import sys, urllib.request, urllib.error, json

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
fails = []

def call(method, path, body=None, headers=None):  # noqa: D401
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})})
    def parse(raw):
        try: return json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError): return {"_raw_bytes": len(raw)}
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, parse(r.read())
    except urllib.error.HTTPError as e:
        return e.code, parse(e.read())

def check(label, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"  {extra}" if extra and not cond else ""))
    if not cond: fails.append(label)

s, b = call("GET", "/health")
check("health endpoint responds", s == 200 and b.get("status") == "ok", str(b))
check("health reports model state", b.get("model") == "unavailable", str(b))

s, b = call("GET", "/")
check("frontend index is served", s == 200 and b.get("_raw_bytes", 0) > 1000, str(b))

s, b = call("POST", "/api/v1/assessments",
            {"age": 11, "symptoms": ["thirst", "urination"],
             "urgent_signs": ["vomiting", "rapid_breathing"]})
check("DKA pattern returns emergency", s == 200 and b.get("emergency") is True, str(b))

s, b = call("POST", "/api/v1/assessments",
            {"age": 11, "glucose_test_type": "fasting", "glucose_mgdl": 240})
check("diagnostic glucose returns urgent", s == 200 and b.get("tier") == "urgent", str(b))
check("no probability FIELD is returned", "probability" not in b and "probability" not in (b.get("model") or {}), str(b))
check("result is flagged rule-based", b.get("source") == "rule_based_thresholds", str(b))

s, b = call("POST", "/api/v1/assessments", {"age": 11, "glucose_mgdl": 240})
check("glucose without test type is rejected", s == 422, str(b))

s, b = call("GET", "/api/v1/facilities")
check("facility list responds", s == 200 and "attribution" in b, str(b))

s, b = call("POST", "/api/v1/facilities",
            {"name": "Unauthorised Clinic", "facility_type": "Clinic", "municipality": "Surallah"})
check("unauthenticated facility write is refused", s in (401, 503), f"got {s} {b}")

s, b = call("GET", "/api/v1/admin/metrics")
check("admin metrics is protected", s in (401, 503), f"got {s} {b}")

s, b = call("POST", "/api/v1/chat", {"message": "how much insulin should I take"})
check("chatbot refuses dosing", s == 200 and b.get("refused") is True, str(b))

s, b = call("POST", "/api/v1/chat", {"message": "what is hba1c"})
check("chatbot answers from corpus", s == 200 and b.get("matched_topic") == "hba1c", str(b))

for asset in ("/assets/styles.css", "/assets/app.js", "/assets/charts.js"):
    s, b = call("GET", asset)
    check(f"{asset} is served", s == 200 and b.get("_raw_bytes", 0) > 200, f"got {s} {b}")

s, b = call("GET", "/manifest.webmanifest")
check("PWA manifest is served and valid", s == 200 and b.get("start_url") == "/", f"got {s}")

s, b = call("GET", "/api/v1/chat/topics")
check("chat corpus is loaded with sources", s == 200 and b.get("topic_count", 0) >= 25
      and all("source" in t for t in b.get("topics", [])), str(b)[:200])
check("LLM is reported as unconfigured", b.get("llm_configured") is False, str(b)[:120])

s, b = call("POST", "/api/v1/chat", {"message": "he is vomiting and what dose of insulin"})
check("emergency outranks refusal", s == 200 and b.get("matched_topic") == "emergency", str(b)[:160])

s, b = call("POST", "/api/v1/chat", {"message": "where can I get tested"})
check("retrieval handles natural phrasing", s == 200 and b.get("matched_topic") == "testing_centers", str(b)[:160])

s, b = call("POST", "/api/v1/chat", {"message": "ano ang type 1 diabetes"})
check("local-language trigger resolves", s == 200 and b.get("matched_topic") == "what_is_t1d", str(b)[:160])

for asset in ("/assets/candie.png", "/assets/candie-avatar.png"):
    s, b = call("GET", asset)
    check(f"{asset} is served", s == 200 and b.get("_raw_bytes", 0) > 5000, f"got {s}")

s, b = call("POST", "/api/v1/chat",
            {"message": "what is the prognosis after a kidney transplant"})
check("uncovered clinical question is declined, not improvised",
      s == 200 and b.get("route") == "declined", str(b)[:160])

s, b = call("POST", "/api/v1/chat", {"message": "help me write my presentation slides"})
check("non-clinical miss offers related topics without a model",
      s == 200 and b.get("route") == "suggestions", str(b)[:160])

s, b = call("POST", "/api/v1/chat", {
    "message": "who is it for",
    "history": [{"role": "user", "content": "tell me about the project"},
                {"role": "assistant", "content": "DiabetEASE is a research prototype."}]})
check("conversation history is accepted", s == 200, str(b)[:160])

s, b = call("POST", "/api/v1/chat",
            {"message": "hi", "history": [{"role": "user", "content": "x"}] * 20})
check("oversized history is rejected", s == 422, f"got {s}")

s, b = call("POST", "/api/v1/auth/register",
            {"username": "smoke_patient", "password": "a-long-enough-pw"})
check("self-registration creates a patient", s in (201, 409) and (s == 409 or b.get("role") == "patient"), str(b)[:140])

s, b = call("POST", "/api/v1/auth/login", {"username": "smoke_patient", "password": "a-long-enough-pw"})
check("patient can log in", s == 200 and b.get("role") == "patient", str(b)[:140])
patient_token = b.get("token", "")

s, b = call("GET", "/api/v1/admin/metrics", headers={"Authorization": "Bearer " + patient_token})
check("patient is blocked from evaluation metrics", s == 403, f"got {s}")

s, b = call("POST", "/api/v1/facilities", {"name": "X", "facility_type": "Clinic", "municipality": "Surallah"},
            headers={"Authorization": "Bearer " + patient_token})
check("patient is blocked from writing facilities", s == 403, f"got {s}")

s, b = call("POST", "/api/v1/auth/register", {"username": "shortpw_user", "password": "abc"})
check("short password is rejected", s == 422, f"got {s}")

s, b = call("GET", "/health")
check("health reports whether accounts are enabled", "accounts_enabled" in b, str(b)[:140])

s, b = call("GET", "/api/v1/facilities/nearby?municipality=Surallah&limit=3")
check("nearby endpoint returns a distance basis", s == 200 and "distance_basis" in b, str(b)[:140])

s, b = call("GET", "/api/v1/facilities/nearby?municipality=Atlantis")
check("nearby rejects an uncovered municipality", s == 404, f"got {s}")

s, b = call("GET", "/api/v1/facilities?kind=pharmacy&limit=500")
check("kind filter returns only pharmacies",
      s == 200 and all(f["facility_type"] == "Pharmacy" for f in b.get("items", [])), str(b)[:120])

s, b = call("POST", "/api/v1/chat", {"message": "where can I get tested in Surallah"})
check("Candie answers a location question from the database",
      s == 200 and b.get("matched_topic") == "facility_lookup" and b.get("grounded") is True, str(b)[:160])

s, b = call("POST", "/api/v1/chat", {"message": "I live in Surallah, what is HbA1c?"})
check("a medical question naming a town is not treated as a lookup",
      s == 200 and b.get("matched_topic") == "hba1c", str(b)[:160])

s, b = call("POST", "/api/v1/assessments",
            {"age": 15, "glucose_test_type": "fasting", "glucose_mgdl": 45})
check("very low glucose is flagged", s == 200 and b.get("tier") == "urgent", str(b)[:120])

s, b = call("GET", "/api/v1/sources")
check("source registry is served with check dates",
      s == 200 and b.get("checked_on") and len(b.get("sources", {})) >= 6, str(b)[:120])

s, b = call("GET", "/api/v1/assessments/thresholds")
check("thresholds cite the 2026 edition", s == 200 and "2026" in b.get("source", ""), str(b)[:160])

s, b = call("POST", "/api/v1/chat", {"message": "is the test covered by philhealth"})
check("Candie explains PhilHealth coverage",
      s == 200 and b.get("matched_topic") == "philhealth", str(b)[:140])

s, b = call("GET", "/api/openapi.json")
check("OpenAPI document is generated", s == 200 and "paths" in b)

print()
print(f"{'FAILED: ' + ', '.join(fails) if fails else 'all end-to-end checks passed'}")
sys.exit(1 if fails else 0)
