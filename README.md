# RAG_demo · 企业合规智能平台

基于 **Vue 3 + FastAPI + Dify** 的企业合规智能平台，围绕法规/规章制度问答、合同审查、合规咨询、合同与规章制度生成等场景，把「知识库 → 检索 → 多步推理 → 成稿」串成一条可用的业务链路。

## 功能范围

| # | 场景 | 实现方式 |
| --- | --- | --- |
| ① | 规章制度学习 | 文档上传 → 解析 → 入 Dify 知识库 |
| ② | 合同审查 | Dify 提取文档、切块并逐块检索审查；后端校验依据与汇总风险 |
| ③ | 规章制度审查 | RAG 问答 |
| ④ | 合规性咨询 | RAG 问答 |
| ⑤ | 内容纠错 | 人工纠错回写知识库 + RBAC 权限 |
| ⑥ | 合同模板库 | 模板导入（Word 表单域 / `#` 占位符）、模板管理 |
| ⑦ | 合同生成 | `docxtpl` 模板填充 |
| ⑧ | 规章制度生成 | 大纲生成 + `python-docx` 排版 |
| ⑨ | 知识库维护 | 知识库持续增删改 |

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端（Web） | Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router 4 |
| 后端 | Python 3.11+ / FastAPI（异步 + SSE 流式） |
| AI 编排 | Dify（自托管，内置知识库 + 工作流/Agent） |
| 文档处理 | `python-docx`、`docxtpl`；解析以 Dify 内置为主 |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |

## 目录结构

```
RAG_demo/
├── frontend/         # Web 端（全部业务页面）
├── backend/          # FastAPI：api/ services/ models/ schemas/ core/
├── dify/             # 工作流 DSL 导出、知识库配置说明、导入脚本
├── data/             # 示例语料（法律法规、合同范本、审核规则等）
├── docs/             # 实现思路与踩坑记录
├── start.command     # 一键重启脚本（停旧服务 → Dify → 后端 → 前端）
└── AGENTS.md         # 项目开发约定（分层、命名、Git 规范）
```

## 快速开始

### 0. 前置

- Docker Desktop（跑 Dify）
- Python 3.11+、Node.js 18+

### 1. 一键启动（macOS）

```bash
./start.command
```

按顺序：停掉在跑的后端/前端 → 拉起 Dify 容器 → 等 Dify 就绪 → 起后端 `:8000` → 起前端 `:5173`，最后自动打开浏览器。日志与 PID 落在 `.run/`（已忽略，不入库）。

### 2. 手动启动

```bash
# 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填 DIFY_BASE_URL / DIFY_API_KEY / 各应用 Key
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

- 后端接口文档：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /api/v1/health`
- Dify 控制台：`http://localhost`

`frontend` 的 Vite 开发服务器已配置代理，`/api` 转发到 `http://127.0.0.1:8000`，因此本地开发无需改 `VITE_API_BASE_URL`。

## 配置

所有真实密钥只存本地 `.env`，不入库；每个服务都提供 `.env.example` 作为模板。

- `backend/.env`：`DIFY_BASE_URL`、知识库 `DIFY_API_KEY`、各业务应用的 API Key（按场景隔离）、`DATASET_ID_*`、`JWT_SECRET`、种子账号等。
- `frontend/.env`：`VITE_API_BASE_URL`（开发期留空走代理）。

## 文档

| 文档 | 内容 |
| --- | --- |
| `AGENTS.md` | 项目开发约定：分层职责、API 约定、前端规范、Git 规范 |
| `docs/Dify应用与工作流设计.md` | Dify 应用与工作流的编排设计 |
| `docs/合同模板导入与合同生成实现思路.md` | 模板导入与合同生成链路 |
| `docs/PDF中文字体渲染问题排查经验.md` | docx → PDF 中文渲染踩坑 |

## 许可证

内部项目，未声明开源许可证。
