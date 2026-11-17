from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import AdminUser
from ..schemas import LoginRequest, TokenResponse
from ..security import TOKEN_TTL_SECONDS, make_token, read_token, verify_password

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(authorization: str = Header(default="")) -> dict:
    """Server-side authorisation. Hiding a button in the UI is not access control.

    Kept as a thin wrapper so there is exactly one place that decides what a role
    may do: an earlier version checked only that the token was valid, which let a
    patient account write facility records.
    """
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin access is not configured")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    payload = read_token(settings.secret_key, authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    if payload.get("role") not in ("researcher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "this endpoint requires a researcher or admin account")
    return payload


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    if not settings.admin_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin access is not configured")

    user = db.query(AdminUser).filter(AdminUser.username == body.username).one_or_none()
    stored_hash = user.password_hash if user else settings.admin_password_hash
    role = user.role if user else "researcher"
    username_ok = bool(user) or body.username == settings.admin_username

    # Always run the hash comparison so a wrong username and a wrong password cost
    # the same time; otherwise the endpoint leaks which usernames exist.
    password_ok = verify_password(body.password, stored_hash)
    if not (username_ok and password_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    return TokenResponse(
        token=make_token(settings.secret_key, body.username, role),
        expires_in=TOKEN_TTL_SECONDS,
        role=role,
    )


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), admin: dict = Depends(require_admin)) -> dict:
    """Researchers and admins may read evaluation metrics; patients may not."""
    if admin.get("role") == "patient":
        from fastapi import HTTPException
        raise HTTPException(403, "evaluation metrics require a researcher or admin account")
    from ..models import Facility, FacilityService, ModelEvaluation, ModelVersion

    total = db.query(Facility).count()
    by_status = {
        s: db.query(Facility).filter(Facility.status == s).count()
        for s in ("verified", "unconfirmed", "outdated")
    }
    confirmed_services = db.query(FacilityService).filter(FacilityService.confirmed.is_(True)).count()

    active = db.query(ModelVersion).filter(ModelVersion.is_active.is_(True)).one_or_none()
    model_block: dict = {"status": "no active model", "metrics": {}}

    # Versions that were trained and measured but deliberately not activated.
    # These used to be dropped on the floor, which made the registry look as
    # though no model had ever been tried. The measurements are the finding, so
    # they are reported whether or not anything is serving.
    evaluated = []

    # The committed report first: a fresh deployment has an empty database, and
    # without this the registry would claim no model had ever been tried.
    report = Path(__file__).resolve().parents[1] / "data" / "model_evaluation.json"
    if report.exists():
        try:
            doc = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        for v in doc.get("versions", []):
            best = max(
                (r for r in v.get("results", []) if not r["model"].startswith("baseline")),
                key=lambda r: r.get("roc_auc", 0), default=None,
            )
            evaluated.append({
                "version": v.get("version"),
                "algorithm": (best or {}).get("model"),
                "prediction_task": v.get("prediction_task"),
                "dataset_label": "DiabetEASE synthetic South Cotabato cohort",
                "dataset_is_synthetic": True,
                "n": doc.get("cohort", {}).get("n"),
                "activated": bool(v.get("activated")),
                "limitations": None,
                "metrics": {
                    f"{r['model']}.{m}": r[m]
                    for r in v.get("results", [])
                    for m in ("roc_auc", "sensitivity", "specificity", "accuracy")
                    if m in r
                },
                "results": v.get("results", []),
                "cohort": doc.get("cohort"),
                "relabelled_from": doc.get("relabelled_from"),
            })

    seen = {e["version"] for e in evaluated}
    for mv in (
        db.query(ModelVersion)
        .filter(ModelVersion.is_active.is_(False))
        .order_by(ModelVersion.trained_at.desc())
        .all()
    ):
        rows = db.query(ModelEvaluation).filter(
            ModelEvaluation.model_version_id == mv.id
        ).all()
        if mv.version in seen:
            # already reported from the committed file; add what only the
            # registry holds rather than listing the version twice
            for e in evaluated:
                if e["version"] == mv.version:
                    e["limitations"] = mv.limitations
                    e["dataset_label"] = mv.dataset_label
            continue
        evaluated.append({
            "version": mv.version,
            "algorithm": mv.algorithm,
            "prediction_task": mv.prediction_task,
            "dataset_label": mv.dataset_label,
            "dataset_is_synthetic": mv.dataset_is_synthetic,
            "n": (mv.n_train or 0) + (mv.n_test or 0),
            "activated": False,
            "limitations": mv.limitations,
            "metrics": {r.metric: r.value for r in rows},
        })

    if active:
        rows = db.query(ModelEvaluation).filter(
            ModelEvaluation.model_version_id == active.id
        ).all()
        model_block = {
            "status": "active",
            "version": active.version,
            "algorithm": active.algorithm,
            "prediction_task": active.prediction_task,
            "dataset_label": active.dataset_label,
            "dataset_is_synthetic": active.dataset_is_synthetic,
            "n_train": active.n_train,
            "n_test": active.n_test,
            "limitations": active.limitations,
            "metrics": {r.metric: r.value for r in rows},
        }

    return {
        "facilities": {
            "total_records": total,
            "by_status": by_status,
            "confirmed_service_claims": confirmed_services,
            "coverage_denominator": (
                "unknown: the true number of health facilities in the ten municipalities "
                "has not been established, so no coverage percentage is reported"
            ),
        },
        "model": model_block,
        "evaluated_not_activated": evaluated,
        "usability_evaluation": {"status": "not conducted", "respondents": 0},
    }
