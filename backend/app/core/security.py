"""JWT 鉴权工具：签发与解析令牌。"""

from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = settings.JWT_ALGORITHM


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析并校验令牌，失败抛出 jwt 异常。"""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
