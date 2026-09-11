# backend（FastAPI）

企业合规智能平台后端，分层：`api/`（路由）→ `services/`（业务）→ `models/`（ORM）。

## 目录结构

```
app/
├── api/          # 路由层：对话/知识库/审查/生成/模板/鉴权/健康检查
├── services/     # 业务层：dify 调用、文档解析、Word 生成
├── models/       # SQLAlchemy ORM 模型
├── schemas/      # Pydantic 请求/响应模型
├── core/         # 配置、JWT 鉴权、依赖注入、异常、常量
└── main.py       # 应用入口
```

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # 填写 DIFY_BASE_URL / DIFY_API_KEY 等

uvicorn app.main:app --reload --port 8000
```

启动后访问 `http://127.0.0.1:8000/docs` 查看接口文档，健康检查 `GET /api/v1/health`。

## 约定

- 统一响应 `{ code, message, data }`，`code=0` 表示成功。
- 流式接口使用 SSE（`text/event-stream`），事件为 Dify 的 `message` / `message_end` / `error`。
- 敏感密钥只存 `.env`，不入库、不进 git。
