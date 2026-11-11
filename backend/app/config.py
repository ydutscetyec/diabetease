"""Environment-driven configuration. No secrets live in source."""
from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:          # python-dotenv missing: environment variables still work
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
REPO_DIR = BASE_DIR.parent                                  # project root

# Load backend/.env before any Settings object reads the environment. Without
# this, .env was written but never read, and SECRET_KEY stayed empty.
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)


class Settings:
    def __init__(self) -> None:
        self.app_name = "DiabetEASE API"
        self.api_version = "v1"
        self.build = os.getenv("DIABETEASE_BUILD", "0.2.0-prototype")
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'diabetease.db'}")
        self.secret_key = os.getenv("SECRET_KEY", "")
        self.admin_username = os.getenv("ADMIN_USERNAME", "")
        self.admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
        self.model_path = os.getenv("MODEL_PATH", str(BASE_DIR / "ml" / "artifacts" / "model.joblib"))
        # Data minimisation: assessments are NOT persisted unless explicitly enabled.
        self.store_assessments = os.getenv("STORE_ASSESSMENTS", "false").lower() == "true"
        self.assessment_retention_days = int(os.getenv("ASSESSMENT_RETENTION_DAYS", "90"))
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.serve_frontend = os.getenv("SERVE_FRONTEND", "true").lower() == "true"
        self.frontend_dir = Path(os.getenv("FRONTEND_DIR", str(REPO_DIR / "frontend")))
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        # Lets the assistant answer medical questions that are not in the
        # reviewed corpus, using the connected model's own knowledge.
        # ON by default in this build, at the project owner's request.
        # Set CLINICAL_OPEN_ANSWERS=false in .env to restrict it again.
        self.clinical_open_answers = os.getenv("CLINICAL_OPEN_ANSWERS", "true").lower() == "true"
        self.llm_base_url = os.getenv("LLM_BASE_URL", "")
        self.llm_model = os.getenv("LLM_MODEL", "")

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_username and self.admin_password_hash and self.secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
