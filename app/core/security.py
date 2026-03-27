from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings


class UserRole(str, Enum):
    ADMIN    = "admin"
    ENGINEER = "engineer"
    VIEWER   = "viewer"


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, role: UserRole, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "role": role.value,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


ROLE_HIERARCHY = {
    UserRole.VIEWER:   0,
    UserRole.ENGINEER: 1,
    UserRole.ADMIN:    2,
}


def has_permission(user_role: str, required_role: UserRole) -> bool:
    try:
        return ROLE_HIERARCHY[UserRole(user_role)] >= ROLE_HIERARCHY[required_role]
    except (ValueError, KeyError):
        return False
