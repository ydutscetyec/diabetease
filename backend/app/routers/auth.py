"""Accounts, roles and session tokens.

Role rules, enforced server-side:
  * self-registration always creates a `patient`; the role field is ignored
  * `researcher` and `admin` are granted only by an existing admin
  * every protected endpoint checks the role in the token, not a UI flag
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import ROLES, Account, AssessmentSession
from ..schemas import AccountOut, LoginRequest, RegisterRequest, RoleGrant, TokenResponse
from ..security import TOKEN_TTL_SECONDS, hash_password, make_token, read_token, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")


def current_account(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "accounts are not configured: set SECRET_KEY")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    payload = read_token(settings.secret_key, authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return payload


def require_role(*allowed: str):
    def _dep(account: dict = Depends(current_account)) -> dict:
        if account.get("role") not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"this endpoint requires one of: {', '.join(allowed)}")
        return account
    return _dep


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "set SECRET_KEY to enable accounts")
    if not USERNAME_RE.match(body.username):
        raise HTTPException(422, "username must be 3-64 characters: letters, digits, . _ -")
    if db.query(Account).filter(Account.username == body.username).one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "that username is taken")

    account = Account(
        username=body.username,
        password_hash=hash_password(body.password),
        role="patient",                      # never taken from the request body
        display_name=body.display_name or None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return TokenResponse(
        token=make_token(settings.secret_key, account.username, account.role),
        expires_in=TOKEN_TTL_SECONDS, role=account.role,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "set SECRET_KEY to enable accounts")

    account = db.query(Account).filter(Account.username == body.username).one_or_none()
    if account:
        if not verify_password(body.password, account.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        return TokenResponse(
            token=make_token(settings.secret_key, account.username, account.role),
            expires_in=TOKEN_TTL_SECONDS, role=account.role,
        )

    # Bootstrap admin from the environment, so a fresh install has a way in.
    if settings.admin_configured and body.username == settings.admin_username:
        if verify_password(body.password, settings.admin_password_hash):
            return TokenResponse(
                token=make_token(settings.secret_key, body.username, "admin"),
                expires_in=TOKEN_TTL_SECONDS, role="admin",
            )
    # Same error and roughly the same cost either way: no username enumeration.
    verify_password(body.password, hash_password("decoy"))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")


@router.get("/me", response_model=AccountOut)
def me(account: dict = Depends(current_account), db: Session = Depends(get_db)) -> AccountOut:
    row = db.query(Account).filter(Account.username == account["sub"]).one_or_none()
    return AccountOut(
        username=account["sub"], role=account["role"],
        display_name=row.display_name if row else None,
        is_env_admin=row is None,
    )


@router.post("/grant", response_model=AccountOut)
def grant_role(body: RoleGrant, db: Session = Depends(get_db),
               admin: dict = Depends(require_role("admin"))) -> AccountOut:
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    row = db.query(Account).filter(Account.username == body.username).one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such account")
    row.role = body.role
    row.granted_by = admin["sub"]
    db.commit()
    return AccountOut(username=row.username, role=row.role,
                      display_name=row.display_name, is_env_admin=False)


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db),
                  admin: dict = Depends(require_role("admin"))) -> dict:
    rows = db.query(Account).order_by(Account.created_at.desc()).limit(200).all()
    return {"items": [{"username": a.username, "role": a.role,
                       "display_name": a.display_name,
                       "created_at": a.created_at, "granted_by": a.granted_by} for a in rows]}


@router.delete("/me", status_code=200)
def delete_me(account: dict = Depends(current_account), db: Session = Depends(get_db)) -> dict:
    """Delete the account and every assessment attached to it."""
    row = db.query(Account).filter(Account.username == account["sub"]).one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no stored account to delete")
    removed = db.query(AssessmentSession).filter(
        AssessmentSession.account_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"deleted": True, "assessments_removed": removed}
