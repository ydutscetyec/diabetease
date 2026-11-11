from __future__ import annotations
import os
import tempfile
from pathlib import Path
import pytest

TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{TMP/'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-not-for-production"
os.environ["ADMIN_USERNAME"] = "tester"
os.environ["MODEL_PATH"] = str(TMP / "absent-model.joblib")
os.environ["SERVE_FRONTEND"] = "false"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"

from app.security import hash_password  # noqa: E402
os.environ["ADMIN_PASSWORD_HASH"] = hash_password("correct-horse-battery")

from fastapi.testclient import TestClient  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Municipality  # noqa: E402
from app.services import llm  # noqa: E402

# Prevent local Ollama detection in tests by default. 
# Tests that need the LLM will monkeypatch llm.available to True.
if not hasattr(llm, "_original_detect_local"):
    llm._original_detect_local = llm._detect_local
llm._detect_local = lambda: ("", "")

@pytest.fixture(scope="session", autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    for name, lat, lon in [("Surallah", 6.374, 124.747), ("Polomolok", 6.217, 125.063),
                           ("Banga", 6.422, 124.779)]:
        db.add(Municipality(name=name, centroid_lat=lat, centroid_lon=lon))
    db.commit()
    db.close()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login",
                    json={"username": "tester", "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return r.json()["token"]