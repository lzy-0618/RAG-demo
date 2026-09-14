"""FastAPI 应用入口。"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.constants import ROLE_EXPERT, ROLE_USER
from app.core.exceptions import BizError
from app.core.security import hash_password
from app.models.base import Base, SessionLocal, engine
from app.models.user import User

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


def seed_users() -> None:
    """幂等创建种子账号（expert / user）。

    仅创建不存在的账号，不覆盖已有密码，避免重启后把改过的口令重置回去。
    密码来自 .env 的 SEED_*_PASSWORD，留空则跳过该账号。
    """
    from sqlalchemy import select

    seeds = [
        (settings.SEED_EXPERT_USERNAME, settings.SEED_EXPERT_PASSWORD, ROLE_EXPERT),
        (settings.SEED_USER_USERNAME, settings.SEED_USER_PASSWORD, ROLE_USER),
    ]
    with SessionLocal() as db:
        for username, password, role in seeds:
            if not username or not password:
                continue
            exists = db.execute(select(User).where(User.username == username)).scalars().first()
            if exists:
                continue
            db.add(User(username=username, hashed_password=hash_password(password), role=role))
            logger.warning("已创建种子账号 %s（角色 %s），请尽快修改默认密码", username, role)
        db.commit()


@app.on_event("startup")
def on_startup() -> None:
    """启动时创建数据表（生产环境应迁移到 Alembic）并初始化种子账号。"""
    Base.metadata.create_all(bind=engine)
    seed_users()


@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )
