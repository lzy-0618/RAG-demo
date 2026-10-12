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

    # 种子账号（启动时幂等创建；密码留空则不创建该账号，生产环境请改掉默认值）
    SEED_EXPERT_USERNAME: str = "expert"
    SEED_EXPERT_PASSWORD: str = ""
    SEED_USER_USERNAME: str = "user01"
    SEED_USER_PASSWORD: str = ""

    # Dify
    DIFY_BASE_URL: str = "http://localhost"
    DIFY_API_KEY: str = ""
    DIFY_TIMEOUT: int = 60

    # Dify 应用级 API Key（按业务场景隔离，未配置时回退到 DIFY_API_KEY）
    DIFY_CHAT_APP_KEY: str = ""
    DIFY_CONTRACT_REVIEW_APP_KEY: str = ""
    DIFY_REGULATION_REVIEW_APP_KEY: str = ""
    DIFY_GENERATE_APP_KEY: str = ""
    # 应用六：合同模板结构化（导入时识别待填字段）
    DIFY_TEMPLATE_STRUCTURE_APP_KEY: str = ""

    # 知识库 dataset_id（与 dify/ 下的 5 个知识库一一对应）
    DATASET_ID_LAW: str = ""
    DATASET_ID_REGULATION: str = ""
    DATASET_ID_CASE: str = ""
    DATASET_ID_RULE: str = ""
    DATASET_ID_EXPERT: str = ""

    # 知识库 / 向量
    EMBEDDING_MODEL: str = ""

    # CORS（开发期允许本地前端）
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 文件上传
    UPLOAD_DIR: str = "uploads"
    # 合同模板目录（需求⑥）与生成产物目录（需求⑦⑧）与上传目录分开
    TEMPLATE_DIR: str = "templates"
    OUTPUT_DIR: str = "outputs"
    # 合同"按当前取值"的草稿预览（内容哈希命名，天然去重）
    CONTRACT_PREVIEW_DIR: str = "var/contract-preview"
    MAX_UPLOAD_SIZE_MB: int = 100

    # 文档预览：docx → PDF（LibreOffice headless）
    # 留空自动探测 PATH 与 macOS 应用路径
    LIBREOFFICE_BIN: str = ""
    # 字体目录，逗号分隔；留空按平台自动探测。容器内应显式指向 /usr/share/fonts
    PDF_FONT_DIRS: str = ""
    # 复用同一 soffice 进程内 profile（见 docs/PDF中文字体渲染问题排查经验.md 第 5 节）
    PDF_PROFILE_DIR: str = "var/lo-profile"
    PDF_CACHE_DIR: str = "var/pdf-cache"
    PDF_CONVERT_TIMEOUT: int = 120
    # soffice 共用 profile 会锁冲突，同一进程内必须串行
    PDF_CONVERT_CONCURRENCY: int = 1
    # 中文墨迹自检阈值（比例低于此值判定字形缺失，见经验文档第 4 节）
    PDF_CJK_INK_MIN_RATIO: float = 0.005


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
