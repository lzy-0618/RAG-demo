# 项目规则（RAG_demo）

> 本文件是 RAG_demo 项目的开发约定与参考规范，后续所有开发工作都应遵循。
> 需求背景见同目录 `功能需求.md`（9 条智能问答/合规场景）。

## 1. 项目定位

基于 **前端 UI + FastAPI 后端 + Dify** 实现企业合规智能平台，覆盖：法规/规章制度检索问答、合同审查、合规咨询、内容纠错、合同模板库、合同/规章制度生成、知识库维护。

**最终技术栈（已确定）**

| 层 | 选型 |
| --- | --- |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router 4 |
| 后端 | Python 3.11+ FastAPI（异步、SSE 流式） |
| AI 编排 | Dify（Docker 自托管 + 内置知识库 + 工作流/Agent） |
| 文档生成 | python-docx + docxtpl（模板填充） |
| 文档解析 | Dify 内置解析为主，复杂法务文档接 unstructured/MinerU |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 部署 | docker-compose（前端 + 后端 + Dify + 基础设施） |

## 2. 目录结构（权威版）

```
RAG_demo/
├── frontend/                 # Web 端（Vue3 + Element Plus），完整 6 个业务页面
│   └── src/
│       ├── api/              # axios 请求封装（按模块：chat/knowledge/generate/…）
│       ├── views/            # 页面：登录、问答、知识库、审查、生成、模板
│       ├── components/       # 通用组件（聊天流式渲染、审查面板等）
│       ├── stores/           # Pinia 状态
│       ├── router/           # Vue Router
│       └── main.ts
├── backend/                  # FastAPI
│   └── app/
│       ├── api/              # 路由层：对话/上传/生成/纠错/权限（只做参数校验与转发）
│       ├── services/         # 业务层：dify 调用、文档解析、word 生成
│       ├── models/           # SQLAlchemy 数据模型
│       ├── schemas/          # Pydantic 请求/响应模型
│       ├── core/             # 配置、鉴权、依赖注入、常量
│       └── main.py           # 应用入口
├── dify/                     # 工作流 DSL 导出、知识库配置说明、导入脚本
├── docker-compose.yml        # 前端 + 后端 + Dify + 数据库
├── Reference code/           # 参考项目（cosmetics-ai、Dify-Web，只读参考）
├── 功能需求.md               # 需求原文
└── AGENTS.md                 # 本文件
```

## 3. 后端规范（backend/）

### 3.1 分层职责

- `api/`（路由层）：仅做参数校验（Pydantic）、鉴权依赖、调用 service，不写业务逻辑。
- `services/`（业务层）：所有业务逻辑，尤其是 Dify 调用、文档解析、Word 生成。
- `models/`：SQLAlchemy ORM 模型，一个文件对应一张表/一个领域实体。
- `schemas/`：Pydantic 请求/响应模型，与 models 分离。
- `core/`：配置加载（pydantic-settings）、JWT 鉴权、依赖注入、异常处理、常量。

### 3.2 关键依赖

```
fastapi
uvicorn[standard]
sqlalchemy
pydantic
pydantic-settings
python-dotenv
dify-client            # Dify 官方 Python SDK
python-multipart       # 文件上传
sse-starlette          # 后端 SSE 流式转发
python-docx            # Word 生成
docxtpl                # Word 模板填充
# 解析（按需）
# unstructured / pymupdf / python-docx
```

### 3.3 API 约定

- 统一前缀 `/api/v1/`，RESTful 风格。
- 统一响应结构：`{ "code": 0, "message": "ok", "data": ... }`；错误用非 0 code + 恰当 HTTP 状态码。
- 流式接口用 SSE：`text/event-stream`，事件格式参考 Dify 的 `message` / `message_end` / `error`。
- 鉴权：JWT（`Authorization: Bearer <token>`），通过 FastAPI 依赖注入到路由。
- 所有外部密钥（Dify API Key 等）只存 `.env`，不硬编码、不入库、不进 git。

### 3.4 Dify 调用封装（重点）

- 统一封装在 `services/dify.py`，对外只暴露业务方法（如 `chat_stream()`、`run_workflow()`、`upload_knowledge()`），隔离 dify-client 细节。
- 知识库操作走 Dify 知识库 API（上传文档、查询、删除），不要把 Dify 当成纯向量库自建检索链路。
- 后端到前端的流式转发：订阅 dify-client 的流式响应 → 通过 sse-starlette 转成 SSE 推给前端，不要在内存里攒完整答案再一次性返回。

## 4. 前端规范（frontend/）

- Vue 3 **Composition API**（`<script setup lang="ts">`），不用 Options API。
- 目录约定：`api/` 只放 axios 封装与接口定义；页面放 `views/`；可复用 UI 放 `components/`；全局状态放 `stores/`。
- 聊天界面用 SSE（`EventSource` 或 `fetch` 流式读取）渲染流式输出，支持 markdown 渲染。
- 文件上传统一走一个上传组件，统一处理进度、错误、重试。
- 权限相关：前端路由守卫 + 按钮级权限，权限来源为后端 RBAC 返回的角色。

`frontend/` 承载全部业务页面。

## 5. Dify 集成规范（dify/）

- 自托管：以 `langgenius/dify` 官方 docker-compose 为准，不魔改镜像。
- 工作流/Agent 的编排用 Dify 控制台完成，导出 DSL 存到 `dify/` 目录做版本管理。
- 知识库配置（分块策略、索引方式、embedding 模型）在 `dify/` 下写说明文档。
- 每个「应用」对应一个业务场景（如合同审查工作流），API Key 按应用隔离。

## 6. 需求 → 模块映射

| 功能需求 | 实现模块 | 关键机制 |
| --- | --- | --- |
| ① 规章制度学习 | 知识库/解析服务 | 上传→解析→入库 Dify |
| ② 合同审查 | 合同审查服务 | Dify 工作流（检索+多步推理） |
| ③ 规章制度审查 | 知识库/对话服务 | RAG 问答 |
| ④ 合规性咨询 | 对话服务 | RAG 问答 |
| ⑤ 内容纠错 | 纠错反馈服务 + 权限 | 人工纠错→回写知识库，RBAC |
| ⑥ 合同模板库 | 模板库服务 | 模板文件导入/管理 |
| ⑦ 合同生成 | 生成服务 | docxtpl 模板填充 |
| ⑧ 规章制度生成 | 生成服务 | 大纲生成 + python-docx |
| ⑨ 知识库维护 | 知识库服务 | 持续增删改 |

## 7. 环境与配置约定

- 每个服务一个 `.env.example`（提交），真实 `.env`（不提交）由开发者本地生成。
- 后端必配：`DIFY_BASE_URL`、`DIFY_API_KEY`、`DATABASE_URL`、`JWT_SECRET`、`EMBEDDING_MODEL` 等。
- 前端必配：`VITE_API_BASE_URL`（后端地址，经 Vite 代理或 Nginx 转发）。
- Dify 与后端的调用走内网容器网络（docker-compose 内服务名），不暴露公网。

## 8. 开发与 Git 约定

- 分支：`main` 稳定 + 功能分支（`feat/xxx`、`fix/xxx`）。
- 提交信息用中文，格式：`feat: 完成xx功能` / `fix: 修复xx`。
- 不提交：`.venv/`、`node_modules/`、`.env`、`*.pyc`、`.DS_Store`、构建产物（dist/）。
- 代码注释只写「代码本身表达不了的约束」，不写复述逻辑的注释。
- 本项目目录不是 git 仓库，若需版本管理请先 `git init` 并配好 `.gitignore`。

## 9. 参考项目（Reference code/）

- `cosmetics-ai/`：Vue3 + FastAPI + Dify 同类架构参考，重点看 `backend/app/services/dify.py`、`routers/`、`frontend/src/views/`。
- `Dify-Web/`：Vue 版 Dify 聊天前端，重点看流式输出、markdown 渲染。
- `workflows/`（difyhub/workflows）：社区 Dify DSL 工作流库，按场景（数据分析、图像生成、文本处理、视觉等）分类。
- `awesome-dify-workflow/`（aircrushin/awesome-dify-workflow）：精选 Dify 工作流 DSL 模板，DSL 文件在 `DSLs/` 目录下。
- 以上均为**只读参考**，不直接作为生产依赖；参考其分层与实现思路，代码按本项目规范重写。
- 编写 Dify DSL 文件时，可到 `workflows/`、`awesome-dify-workflow/` 两个仓库中找类似文件进行参考。

## 10. 分阶段实施顺序

1. **Phase 1（MVP）**：后端骨架 + Dify 对接 + 文档上传入库 + RAG 流式问答（需求 ①③④）。
2. **Phase 2**：合同审查工作流（②）+ 内容纠错反馈与权限（⑤）。
3. **Phase 3**：合同模板库 + 合同/规章制度 Word 生成（⑥⑦⑧）+ 知识库维护完善（⑨）。
