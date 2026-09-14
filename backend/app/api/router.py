"""路由聚合：所有业务路由挂载到统一前缀 /api/v1。"""

from fastapi import APIRouter

from app.api import auth, chat, correction, generate, health, knowledge, review, template

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(correction.router)
api_router.include_router(knowledge.router)
api_router.include_router(review.router)
api_router.include_router(template.router)
api_router.include_router(generate.router)
