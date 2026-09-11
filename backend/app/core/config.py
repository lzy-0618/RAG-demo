"""应用配置：从环境变量 / .env 加载，敏感信息不落库、不入 git。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    APP_NAME: str = "RAG_demo 企业合规智能平台"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # 数据库
    DATABASE_URL: str = "sqlite:///./rag_demo.db"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Dify
    DIFY_BASE_URL: str = "http://localhost"
    DIFY_API_KEY: str = ""
    DIFY_TIMEOUT: int = 60

    # Dify 应用级 API Key（按业务场景隔离，未配置时回退到 DIFY_API_KEY）
    DIFY_CHAT_APP_KEY: str = ""
    DIFY_REVIEW_APP_KEY: str = ""
    DIFY_GENERATE_APP_KEY: str = ""

    # 知识库 / 向量
    EMBEDDING_MODEL: str = ""

    # CORS（开发期允许本地前端）
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 文件上传
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
