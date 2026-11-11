from __future__ import annotations

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
        "usability_evaluation": {"status": "not conducted", "respondents": 0},
    }
