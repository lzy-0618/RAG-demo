"""FastAPI 依赖注入：鉴权、数据库会话等。"""

from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.models.base import SessionLocal

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """解析 Bearer Token，返回用户标识（subject）。"""
    if credentials is None:
        raise AuthError("缺少 Authorization 头")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AuthError("凭证已过期") from None
    except jwt.PyJWTError:
        raise AuthError("无效凭证") from None
    subject = payload.get("sub")
    if not subject:
        raise AuthError("凭证缺少 subject")
    return subject


def require_admin(current_user: str = Depends(get_current_user)) -> str:
    """管理员权限占位：接入 RBAC 后在此校验角色。"""
    # TODO: 查询用户角色，非管理员抛出 ForbiddenError
    return current_user
