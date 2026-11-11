"""Password hashing (PBKDF2-HMAC-SHA256, stdlib) and signed bearer tokens.

No third-party crypto dependency: fewer moving parts to audit for a project that
one student maintains. If you later need bcrypt or argon2, swap `hash_password`
and `verify_password` only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

import jwt

ITERATIONS = 240_000
TOKEN_TTL_SECONDS = 60 * 60 * 8


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


# ---------------------------------------------------------------- tokens
# PyJWT rather than a hand-rolled HMAC format: the signing is the same HS256,
# but expiry parsing, algorithm confusion and the "none" algorithm attack are
# handled by a library that is audited and widely deployed. Tokens issued by
# the previous custom format are not accepted; everyone signs in again once.
def make_token(secret: str, username: str, role: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
        "iss": "diabetease",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def read_token(secret: str, token: str) -> dict | None:
    """Return the claims, or None for anything not currently valid."""
    try:
        return jwt.decode(
            token, secret,
            algorithms=["HS256"],          # never trust the header's alg
            issuer="diabetease",
            options={"require": ["exp", "sub", "role", "iss"]},
        )
    except jwt.InvalidTokenError:
        return None
