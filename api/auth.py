"""
Authentication primitives — JWT login for the Customer and Investigator roles
(ADR-010, ADR-021). Admin is deliberately NOT here: it is a dashboard-level
demo flag with no token (ADR-010).

Design in four lines:
  - A password is checked against the stored bcrypt hash with passlib.
  - A successful login yields a short-lived HS256 JWT: sub = user id, role.
  - `get_current_user` turns a Bearer token into an AuthUser, or raises 401.
  - `require_customer` / `require_investigator` add the role check (403).

The signing secret comes from the JWT_SECRET environment variable. If it is
missing a clearly named development default is used and ONE warning is logged
at import time — fine for a local demo, never for anything real. Passwords and
tokens are never logged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60

ROLE_CUSTOMER = "customer"
ROLE_INVESTIGATOR = "investigator"
_ROLES = {ROLE_CUSTOMER, ROLE_INVESTIGATOR}

_DEV_DEFAULT_SECRET = "dev-only-secret-change-me"
JWT_SECRET = os.environ.get("JWT_SECRET") or _DEV_DEFAULT_SECRET
if JWT_SECRET == _DEV_DEFAULT_SECRET:
    logger.warning(
        "JWT_SECRET is not set: using the development default secret. "
        "Set the JWT_SECRET environment variable for anything beyond a local demo."
    )

# auto_error=False so a missing header becomes OUR 401 (with WWW-Authenticate),
# not the framework's default.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    user_id: int
    role: str


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.verify(plain, hashed)
    except ValueError:  # malformed / unsupported hash: treat as a failed login
        return False


def create_access_token(user_id: int, role: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + (expires_delta if expires_delta is not None else timedelta(minutes=ACCESS_TOKEN_MINUTES)),
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=ALGORITHM)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = int(claims["sub"])
        role = claims["role"]
    except (JWTError, KeyError, TypeError, ValueError):
        # expired, tampered, malformed, or missing claims: all the same to the caller
        raise _unauthorized() from None
    if role not in _ROLES:
        raise _unauthorized()
    return AuthUser(user_id=user_id, role=role)


def _require_role(user: AuthUser, role: str) -> AuthUser:
    if user.role != role:
        raise HTTPException(status_code=403, detail=f"This endpoint requires the {role} role")
    return user


def require_customer(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return _require_role(user, ROLE_CUSTOMER)


def require_investigator(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return _require_role(user, ROLE_INVESTIGATOR)
