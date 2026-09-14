"""FastAPI 依赖注入：鉴权、数据库会话、权限校验。"""

from collections.abc import Generator
from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.constants import ROLE_EXPERT, ROLE_USER
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.models.base import SessionLocal

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """当前请求的主体：用户名 + 角色（来自 JWT）。"""

    username: str
    role: str

    @property
    def is_expert(self) -> bool:
        return self.role == ROLE_EXPERT


def get_db() -> Generator[Session, None, None]:
    """请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _decode_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> dict:
    if credentials is None:
        raise AuthError("缺少 Authorization 头")
    try:
        return decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AuthError("凭证已过期") from None
    except jwt.PyJWTError:
        raise AuthError("无效凭证") from None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """解析 Bearer Token，返回用户标识（subject）。

    保留字符串返回以兼容既有路由（Dify 的 user 参数、文档 uploader 等）。
    需要角色时用 get_principal / require_expert。
    """
    payload = _decode_credentials(credentials)
    subject = payload.get("sub")
    if not subject:
        raise AuthError("凭证缺少 subject")
    return subject


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """解析 Bearer Token，返回用户名与角色。"""
    payload = _decode_credentials(credentials)
    subject = payload.get("sub")
    if not subject:
        raise AuthError("凭证缺少 subject")
    return Principal(username=subject, role=payload.get("role") or ROLE_USER)


def require_expert(principal: Principal = Depends(get_principal)) -> Principal:
    """内容纠错/专家标注的权限门槛（需求⑤）：仅 expert 角色可访问。"""
    if not principal.is_expert:
        raise ForbiddenError("该操作仅专家角色可用")
    return principal
