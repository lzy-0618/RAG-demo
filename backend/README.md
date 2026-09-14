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

## 登录与角色（RBAC，需求⑤前置）

- 口令哈希：标准库 `hashlib.pbkdf2_hmac`（PBKDF2-HMAC-SHA256，20 万次迭代，随机盐），
  格式 `pbkdf2_sha256$迭代次数$盐$哈希`。用标准库是为避免引入需编译的原生依赖；
  如需换 bcrypt/passlib，只改 `core/security.py` 的 `hash_password` / `verify_password`（可凭前缀迁移存量哈希）。
- 种子账号：启动时幂等创建（仅创建不存在的账号，不覆盖已改密码），账号与密码来自 `.env`：

  ```env
  SEED_EXPERT_USERNAME=expert     # 角色 expert：额外拥有内容纠错/专家标注权限
  SEED_EXPERT_PASSWORD=...
  SEED_USER_USERNAME=user01       # 角色 user
  SEED_USER_PASSWORD=...
  ```

- 令牌：JWT 携带 `sub`（用户名）与 `role`；`LoginResponse` 同时返回 `username` / `role`。
- 依赖注入：`get_current_user()` 返回用户名字符串（兼容既有路由）；需要角色时用
  `get_principal()`（返回 `Principal(username, role)`）或 `require_expert()`（非专家抛 403）。
- 登录失败统一提示「账号或密码错误」，不区分账号是否存在，避免账号枚举。

## 内容纠错 / 专家标注（需求 ⑤，已实现）

专家在聊天页针对某条 AI 回答**就地标注**，提交即写入「专家知识库」（**无审核环节**），
后续 RAG 回答会自动参考该标注——所有接口受 `require_expert` 保护（普通用户 403）。

| 接口 | 说明 |
| --- | --- |
| `POST /api/v1/corrections` | 提交标注（来源回答、修正内容、问题、conversation_id、message_id） |
| `GET /api/v1/corrections` | 标注列表（可按 `expert` / `message_id` 过滤） |
| `POST /api/v1/corrections/{id}/retry` | 写库失败后重试 |
| `DELETE /api/v1/corrections/{id}` | 删除标注（连同其在专家知识库中的文档一起删除） |

实现要点：

- 标注文本组织成自包含结构（用户问题 / 原回答 / **专家修正内容（以此为准）** / 标注人），便于检索命中后模型直接引用；
- `write_status`：`pending → written / failed`，写库失败不丢标注内容，`error` 落库供前端展示与重试；
- `message_id` 串联：聊天页从 SSE 的 `message_end` 保存 Dify 消息 ID，标注据此精确关联到某条回答；
- 闭环验证：标注写入后追问同类问题，回答以「专家修正后的口径」作答并列出专家标注作为依据来源。

> 已知差异：`POST /chat`（阻塞式）返回的 `metadata.retriever_resources` 为空，流式 `/chat/stream` 的
> `sources` 事件正常（前端使用流式）。阻塞式接口当前未被前端使用，待后续排查。

## 模板库与生成（需求 ⑥⑦⑧，已实现）

**合同模板库（⑥）**：模板为含 `{{ 变量 }}` 占位符的 .docx，导入时用 docxtpl 解析占位变量并缓存，
前端据此动态渲染填报表单。文件存 `templates/` 目录（与 uploads/、outputs/ 分开）。

| 接口 | 说明 |
| --- | --- |
| `GET /api/v1/templates` | 列表（分类过滤 + 分页），返回占位变量与全部分类 |
| `POST /api/v1/templates` | 导入模板（multipart：`file` + `name`/`category`/`description`） |
| `PATCH /api/v1/templates/{id}` | 修改模板元信息 |
| `GET /api/v1/templates/{id}/download` | 下载模板原文件 |
| `DELETE /api/v1/templates/{id}` | 删除模板（含文件） |

**合同生成（⑦）**：`POST /api/v1/generate/contract`（`template_id` + `variables`）→ docxtpl 确定性填充，
未填变量按空值处理并通过 `missing_variables` 返回提示。**该链路不调用大模型**。

**规章制度生成（⑧）**：两段式 + 生成后自动合规审查与修正循环。

| 接口 | 说明 |
| --- | --- |
| `POST /api/v1/generate/regulation/outline` | 第一段：按需求生成大纲（同步返回，可编辑确认） |
| `POST /api/v1/generate/regulation/document` | 第二段：生成全文 + 自动审查（后台任务，返回 task_id） |
| `GET /api/v1/generate/regulation/{task_id}` | 轮询进度与结果（含审查冲突清单、章节、下载地址） |
| `GET/DELETE /api/v1/generate/regulation` | 生成历史 / 删除 |
| `GET /api/v1/generate/files/{file_name}` | 下载生成产物（仅限 outputs/ 内文件名，防目录穿越） |

修正循环（循环在后端，Dify 只做单轮生成）：

```
生成首版 → 逐块审查（复用审查管线）→ 合规则结束
        → 不合规：把「冲突清单(≤15 条) + 上一版全文」回传重新生成 → 再审查，最多 3 轮
```

- 回传**必须带 `previous_sections`**：只给冲突清单会让模型整篇重写、可能引入新冲突导致循环不收敛；
- `round` 为已完成的修正轮次（0=首版），`review_round` 为当前轮次审查的第几次；
- 生成产物用 python-docx 程序化排版（`build_docx_from_sections`），无固定模板；
- 生成阶段挂「法规 + 现行制度」检索作写作参照，从源头降低冲突率。

> 三种产物目录约定：`uploads/`（知识库文档与待审查文件）、`templates/`（合同模板）、`outputs/`（生成产物），
> 均已 gitignore。

## 知识库管理（需求 ①⑨，Phase 1 已实现）

| 接口 | 说明 |
| --- | --- |
| `GET /api/v1/knowledge/datasets` | 列出 5 个业务知识库（配置状态 + 本地文档数） |
| `POST /api/v1/knowledge/upload` | 文件入库（multipart：`dataset_key` + `file`） |
| `POST /api/v1/knowledge/text` | 文本入库（审核规则、专家标注等） |
| `GET /api/v1/knowledge/documents` | 本地文档列表（`dataset_key` 过滤 + 分页） |
| `POST /api/v1/knowledge/documents/{id}/refresh` | 轮询 Dify 索引状态并回写 |
| `DELETE /api/v1/knowledge/documents/{id}` | 删除（Dify 与本地同步） |

状态流转：`uploaded → parsing → ready / failed`（Dify 索引异步，需 `refresh` 或前端轮询）。

### Dify 1.17 知识库 API 的四个契约坑（均已实测）

1. **`doc_form` 必须与知识库一致**：Dify 会校验请求的 `doc_form` 是否等于该库的（本项目 5 个库都是
   `hierarchical_model` 父子分段），不一致返回 400 `doc_form is different from the dataset doc_form`。
   实现上先 `GET /v1/datasets/{id}` 取 `doc_form`（进程内缓存）再创建文档。
2. **不要传 `process_rule`**：父子分段的库不接受 custom 规则（报 `pre_processing_rules is required`），
   沿用库自身分段设置即可；`DifyClient._process_rule()` 只在明确要覆盖分段时使用。
3. **`create_by_file` 直接收 multipart 文件**（`file` + `data` JSON 字符串），不是「先上传拿 file_id」；
   `/v1/datasets/upload-file` 在 1.17 不存在。`update_by_*` 的路径是复数 `documents/{id}/`；
   删除成功返回 204（无响应体）。
4. **同名文件会被去重复用**：同一知识库内上传同名文件时，Dify 返回已存在文档的 ID 而不新建。
   若本地直接插新记录，会出现多条记录指向同一 Dify 文档；`_absorb_duplicate()` 会把新记录合并到已有记录，
   这同时让「同名重传」获得正确的更新语义（重新索引已有文档）。

### 本地联调

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
# 另开终端（当前登录为骨架占位，任意账号可签发 token）
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"dev","password":"x"}'
```

> `documents` 表结构在 Phase 1 有变更（新增 `dataset_key` / `doc_type` / `dify_batch` / `error` / `updated_at`）。
> 若本地库是旧结构，删除该空表让启动时的 `create_all` 重建即可。

## 审查服务（需求 ②③，Phase 2 已实现）

| 接口 | 说明 |
| --- | --- |
| `POST /api/v1/review` | 提交审查（multipart：`review_type` + `content` 或 `file`），立即返回 `task_id` |
| `GET /api/v1/review/{task_id}` | 查询进度与结果（前端轮询，`completed`/`failed` 后停止） |
| `GET /api/v1/review/tasks` | 任务列表（历史记录） |
| `DELETE /api/v1/review/{task_id}` | 删除任务与落地文件 |

管线：**解析 → 切块 → 逐块调 Dify 审查工作流（并发 3）→ 代码合并**，循环与进度都在后端：

- `services/document_parser.py`：PDF 按页（>50 页时 3 页一块）、docx 按段落、文本按行；短文档（≤1.5 万字或 ≤10 页）合并为单块。
- `services/review.py`：`merge_risks()` 按 `(law_name, article)` + 条款文本相似度（≥0.7）跨块去重，按风险等级与块序排序，`build_summary()` 用代码生成结论（不额外调 LLM）。
- 两个审查类型共用同一管线，仅按 `review_type` 选择 `DIFY_CONTRACT_REVIEW_APP_KEY` / `DIFY_REGULATION_REVIEW_APP_KEY`。

### 合规安全网：绝不把「解析失败」当成「无风险」

实测踩过的坑：块太大（3500 字）时，违规分析节点的 JSON 输出会超出 `max_tokens` 被截断，
解析兜底返回空风险列表，整块被静默判为「无风险」——对合规产品是危险的假阴性。

后端现在的处理（`_review_chunk`）：

1. 工作流回传 `parse_error=true` → 该块计为**失败块**；
2. 判定为不合规但风险明细为空（结果自相矛盾）→ 同样计为**失败块**；
3. 只要有失败块，整体 `is_compliant=false`，`summary` 追加「N 个文本块审查失败，建议人工复核」。

配套调整：单块字数由 3500 降到 **2000**（实测 2000 字时识别率与调用次数较平衡）；
两个审查工作流的违规分析节点输出上限提到 8192 并在 prompt 中约束篇幅（见 `dify/dsl/*.yml`）。
