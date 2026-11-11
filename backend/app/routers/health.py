from __future__ import annotations
from fastapi import APIRouter
from sqlalchemy import text
from ..config import get_settings
from ..database import engine
from ..services import inference

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "build": settings.build,
        "database": "reachable" if db_ok else "unreachable",
        "model": inference.status()["status"],
        "admin_configured": settings.admin_configured,
        "accounts_enabled": bool(settings.secret_key),
    }
