"""鉴权路由：登录签发 JWT。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.security import create_access_token
from app.schemas.user import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["鉴权"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """账号密码登录，签发访问令牌。"""
    # TODO: 校验密码哈希（接入 passlib/bcrypt 后），此处为骨架占位
    token = create_access_token(subject=request.username)
    return TokenResponse(access_token=token)
