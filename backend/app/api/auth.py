"""鉴权路由：账号密码登录签发 JWT。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ROLE_USER
from app.core.deps import get_db
from app.core.exceptions import AuthError
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.user import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["鉴权"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """账号密码登录：校验口令哈希，签发携带角色的访问令牌。

    账号不存在与密码错误返回同一提示，避免账号枚举。
    """
    user = db.execute(select(User).where(User.username == request.username)).scalars().first()
    if user is None or not verify_password(request.password, user.hashed_password):
        raise AuthError("账号或密码错误")

    role = user.role or ROLE_USER
    token = create_access_token(subject=user.username, role=role)
    return TokenResponse(access_token=token, username=user.username, role=role)
