"""JWT 鉴权工具与密码哈希：签发/解析令牌、口令校验。"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = settings.JWT_ALGORITHM

# PBKDF2-HMAC-SHA256 参数（标准库实现，不引入需编译的原生依赖）
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """生成口令哈希，格式：pbkdf2_sha256$迭代次数$盐$哈希。

    用标准库实现是为了避免引入需编译的原生扩展；如需换成 bcrypt/passlib，
    只需替换本函数与 verify_password（可凭前缀做存量哈希迁移）。
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """校验口令；哈希串格式非法时返回 False（不抛异常，避免泄露内部细节）。"""
    try:
        prefix, iterations, salt_hex, digest_hex = hashed.split("$")
        if prefix != _PBKDF2_PREFIX:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_access_token(subject: str, role: str = "user", expires_minutes: int | None = None) -> str:
    """签发访问令牌，携带角色用于权限校验。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析并校验令牌，失败抛出 jwt 异常。"""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
