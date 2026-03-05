"""Authentication – JWT tokens, password hashing, FastAPI dependency."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.database import get_db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "phoenix-3-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> Optional[dict]:
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = %s",
            (username,),
        )
        return cur.fetchone()


def create_user_in_db(username: str, password: str, role: str = "user") -> dict:
    hashed = hash_password(password)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role) "
            "VALUES (%s, %s, %s) RETURNING id, username, role",
            (username, hashed, role),
        )
        return cur.fetchone()


def seed_default_admin() -> None:
    """Create the default admin account if it doesn't exist."""
    existing = get_user_by_username("admin")
    if not existing:
        create_user_in_db("admin", "admin", "superadmin")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Decode JWT and return the user record, or 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    with get_db() as conn:
        cur = conn.execute(
            "SELECT id, username, role FROM users WHERE id = %s",
            (int(user_id),),
        )
        user = cur.fetchone()
    if user is None:
        raise credentials_exception
    return dict(user)


def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    """Only allow superadmin role."""
    if user["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")
    return user
