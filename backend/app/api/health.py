"""健康检查。"""

from fastapi import APIRouter

router = APIRouter(tags=["健康检查"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
