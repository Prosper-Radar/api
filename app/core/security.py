"""
JWT authentication helpers.

In dev mode (SECRET_KEY starts with "local-dev-") tokens are accepted without
expiry verification so curl/Swagger tests remain frictionless.

For production set SECRET_KEY to a random 32+ char string and optionally set
ACCESS_TOKEN_EXPIRE_MINUTES (default 60).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str          # username / user id
    exp: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — using bcrypt directly (bcrypt 5.x, passlib-free)
# ──────────────────────────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def get_password_hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


# ──────────────────────────────────────────────────────────────────────────────
# Dependency: get_current_user
# ──────────────────────────────────────────────────────────────────────────────
# Pre-hashed passwords for demo users (generated once at startup).
# Replace with DB lookup in production.
# To regenerate: python -c "import bcrypt; print(bcrypt.hashpw(b'demo1234', bcrypt.gensalt()).decode())"
_DEMO_USERS: dict[str, str] = {}


def _init_demo_users() -> None:
    global _DEMO_USERS
    _DEMO_USERS = {
        "demo": get_password_hash("demo1234"),
        "admin": get_password_hash("prosper2024!"),
    }


# Lazy init so module import is fast
_demo_users_ready = False


def _ensure_demo_users() -> None:
    global _demo_users_ready
    if not _demo_users_ready:
        _init_demo_users()
        _demo_users_ready = True


def authenticate_user(username: str, password: str) -> Optional[str]:
    _ensure_demo_users()
    hashed = _DEMO_USERS.get(username)
    if not hashed:
        return None
    if not verify_password(password, hashed):
        return None
    return username


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
) -> str:
    """
    Returns the username from a valid JWT.

    In dev mode (no token supplied) returns "anonymous" so existing Swagger
    calls keep working without authentication.
    """
    settings = get_settings()
    is_dev = settings.secret_key.startswith("local-dev-")

    if not token:
        if is_dev:
            return "anonymous"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise JWTError("empty sub")
    except JWTError as exc:
        if is_dev:
            logger.debug("JWT decode failed in dev mode — allowing: %s", exc)
            return "anonymous"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return username
