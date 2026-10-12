# Dify 应用与工作流设计指引

> 本文是 RAG_demo「企业合规智能平台」的 Dify 侧开发指引，供在 Dify 控制台（自托管）中实际搭建时对照执行。
> 配套文档：`功能实现策略.md`（整体策略）、`功能需求.md`（需求原文）、`AGENTS.md`（项目规范）。
> 本文覆盖：① 知识库构建 ② Dify 应用/工作流/Agent 设计 ③ API Key 与后端 `.env` 映射 ④ 构建顺序与验证。

---

## 0. 总览

### 0.1 知识库（5 个 dataset）

| # | 知识库名称 | 内容 | 写入方式 | 检索应用 |
| --- | --- | --- | --- | --- |
| 1 | 法律法规库 | 国家法律法规文件 | 人工上传（文件为主） | 合同审查、制度审查 |
| 2 | 某钢规章制度库 | 某钢现行规章制度文件 | 人工上传（文件为主） | 合同审查、制度审查、合规咨询 |
| 3 | 典型案例库 | 典型案例文档 | 人工上传（文件为主） | 合同审查 |
| 4 | 审核规则库 | 若干审核规则 | 人工添加（**文本为主**） | 暂无应用挂载（待后续应用使用） |
| 5 | 专家知识库 | 专家对 AI 回答的纠错内容 | 纠错模块自动写入 | 合规咨询 |

### 0.2 Dify 应用（4 个核心）

| # | 应用名 | 类型 | 对应需求 | API Key（`.env`） |
| --- | --- | --- | --- | --- |
| 1 | 合规咨询 | **Chatflow** | ④ | `DIFY_CHAT_APP_KEY` |
| 2 | 合同审查 | **Workflow** | ② | `DIFY_CONTRACT_REVIEW_APP_KEY` |
| 3 | 制度审查 | **Workflow** | ③ | `DIFY_REGULATION_REVIEW_APP_KEY` |
| 4 | 规章制度生成 | **Workflow** | ⑧ | `DIFY_GENERATE_APP_KEY` |

> 原方案中的「审查汇总」（②③ 长文档跨块结果合并）**决定不建 Dify 应用**，由后端代码实现合并去重，见第 5 节。
>
> 合同生成（⑦）默认走 docxtpl 纯模板填充，**不需要 Dify 应用**；如需 AI 辅助生成条款正文，再另行增加。

---

## 1. 知识库构建

### 1.1 通用配置

- **索引方式**：全部选「高质量（High Quality）」。
- **Embedding 模型**：选 Dify 部署中已接入的支持中文的模型（如 `bge-large-zh`、`text-embedding-3-small` 或国产 embedding），5 个库保持一致。
- **分块策略（文档分段）**：
  - 分块长度（Chunk size）：500～800 token。
  - 相邻分块重叠（Overlap）：10%～15%（法规/合同条文密集，建议 15% 避免条款被截断）。
  - 分隔符：保留默认（段落换行 + 句号等）。
- **检索设置**：
  - Top K：3～5（审查场景可稍大，5；咨询场景 3）。
  - Score Threshold：先不设（0），联调时再按召回质量调。
  - Rerank：若部署了 rerank 模型，审查场景建议开启，提升法条命中率。

### 1.2 各库构建要点

| 知识库 | 建议 |
| --- | --- |
| 法律法规库 | 按「法」为单位上传整份文件；文件命名规范：`《法律名》.pdf/docx`，便于引用来源显示 |
| 某钢规章制度库 | 按「制度」为单位上传；命名：`某钢-制度名.docx` |
| 典型案例库 | 每个案例一份文档，或一个合集；命名：`案例-案由-关键词` |
| 审核规则库 | **以文本为主**：每条规则用「创建文本文档」方式新增，标题 = 规则名称，正文 = 规则内容。可加 `规则类型`、`适用场景` 标签 |
| 专家知识库 | 由后端纠错接口自动写入，无需手工建内容；但**需先创建空 dataset**，并记下其 dataset_id 配置到后端 |

> 每个 dataset 创建后记下 `dataset_id`（知识库 URL 里可见，或通过 `GET /v1/datasets` 查询），后端 `.env` 需配置 5 个 `DATASET_ID_*`（见第 7 节）。

---

## 2. 应用一：合规咨询（Chatflow）

### 2.1 定位

标准 RAG 多轮问答，覆盖差旅 / 接待 / 招采等环节的合规解读。走 `/v1/chat-messages`，支持 `conversation_id` 多轮上下文。

### 2.2 节点编排

```
开始(Start，category)
  → LLM 问题改写（结合多轮对话历史，把追问改写为独立完整问题）
  → Code 改写兜底（改写为空/超长时回退原始提问）
  → 知识检索（某钢规章制度库 + 专家知识库，2 库）
  → LLM 回答（带对话记忆 + category 语境 + 检索上下文）
  → 直接回复(Answer)
```

> Chatflow 的终止节点是 `answer`（不是 `end`）。多轮问题改写节点是为解决 RAG 多轮的典型问题：追问「那住宿标准呢」本身无主语，直接拿去检索召回很差。DSL 见 `dify/dsl/合规咨询.yml`。

### 2.3 输入变量（Start 节点定义）

| 变量 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | text | 是 | 用户提问 |
| `category` | text | 否 | 咨询类别：差旅 / 接待 / 招采（控制 Prompt 语境） |

> `conversation_id` 由 Dify 自动管理，无需在 Start 里定义。

### 2.4 知识检索节点

- 数据集：**某钢规章制度库 + 专家知识库**（2 库）。专家标注库必须挂上，需求⑤「专家纠错下次回答生效」的闭环依赖它。
- Top K：3；Score Threshold：不设。
- 检索 query：多轮改写节点的输出（`code_rewrite.question`），不是原始 `sys.query`。

### 2.5 LLM 节点 Prompt 要点

```
你是某钢集团的企业合规助手。请依据「知识库检索到的内容」回答用户问题，
严格基于检索结果，不臆造；若检索结果不足以回答，明确说明「知识库中暂无相关内容」。
用户咨询类别：{{category}}
用户问题：{{query}}
要求：
1. 回答末尾附「依据来源」清单（法律/制度名称 + 具体条款）。
2. 涉及差旅/接待/招采时，结合审核规则库中的规则给出判断。
```

### 2.6 输出

- `answer`：回答文本（流式逐字返回）。
- 引用来源：Dify 在 `metadata.retriever_resources` 返回，后端 `api/chat.py` 已提取到 `sources`，前端展示引用卡片。
- Chatflow 的 `features.retriever_resource.enabled` 必须为 `true`，否则拿不到引用来源。
- `features` 另含开场白与推荐问题（差旅住宿标准、接待费用上限、招采违规情形、供应商准入）。

---

## 3. 应用二：合同审查（Workflow）

当前部署文件：`dify/dsl/合同审查.yml`。Start 接收 `input_file`（PDF、DOCX、MD 或 TXT）。Dify 文档提取器输出正文，Code 节点按段落切成约 2000 字的文本块，Iteration 对各块分别检索法规、现行制度和典型案例，再由 Qwen 一次生成结构化 `report.risks`。案例只用于辅助分析，风险依据取自法规和制度检索。

该合同审查流程已在 Dify 实例验证。

迭代内最后的 Code 节点将该块原文、报告及三路原始检索结果封装为 JSON 字符串。End 输出 `chunks: array[string]` 和等长的 `results: array[string]`。迭代单项失败时对应结果为空，供后端标记人工复核。

后端上传原始文件、调用一次流式工作流，按 Dify 返回的 `chunks[i]` 校验 `results[i]`：风险原文须属于当前块，法规/制度引用须能在本次检索结果中核对；然后去重、汇总并保存。文本输入先写临时 TXT。旧式 DOC 先转换为 DOCX。后端不再为合同另行解析和切块。

---

## 4. 应用三：制度审查（Workflow，设计已定稿）

### 4.1 定位

对「新规章制度」做单块审查（需求③），**独立应用**，不复用合同审查的 API Key。沿用自身的检索 → 合规判定 → 分支 → 冲突标注流程，核心职责是**冲突检测**。DSL 见 `dify/dsl/制度审查.yml`。差异点：

- 知识检索只挂 **2 库**：法律法规 + 某钢规章制度（无典型案例、审核规则、专家标注）。Top K：5。
- LLM-1 判定语义为冲突检测：与上位法/现行制度存在明确冲突、越权或矛盾才算不合规；纯文字表述、格式问题不算不合规。
- LLM-2 冲突标注：`violations`（law_name/article/description）与合同审查同名同构，**无 `reference_case` 字段**（防编造），`suggestion` 依据被冲突的上位条款给出。
- 输入变量为 `chunk_text`，End 输出 `is_compliant` / `compliance_reason` / `risks` / `parse_error`（`is_compliant` / `compliance_reason` / `risks`），后端审查管线按 `review_type` 换 API Key 即可。

> 已知取舍：专家标注库不进审查应用，需求⑤专家纠错的「下次回答参考」只在合规咨询链路生效。

---

## 5. 审查合并（由后端实现，不建 Dify 应用）

### 5.1 决策

原方案的「审查汇总」Workflow（输入所有块的 risks JSON → LLM 去重合并）**不建**。审查合并由后端代码实现，服务三处：

1. ②③ 长文档逐块审查后的完整报告合并；
2. ⑧ 修正循环回传前的冲突清单清洗（合并去重 → 按等级排序 → 截断 ≤15 条）；
3. 短文档的单次审查结果规整。

### 5.2 后端合并规则（代码实现）

- **结构化字段去重为主**：同一 `(law_name, article)` 且条款原文 `clause` 相同/高度相似的条目合并为一条（violations 并集、suggestion 取更完整者、risk_level 取更高、reference_case 取首个非空）。实现见 `services/review.py::merge_risks()`，相似度阈值 0.7。
- **排序**：按 `risk_level`（high > medium > low）→ 块顺序（chunk_index）。
- **`summary`**：由代码按风险数量与等级分布生成模板化结论，不调 LLM。
- **失败块不掩盖**：只要有块判定失败（或 `parse_error=true`），整体 `is_compliant=false` 且结论中提示人工复核——合规场景不允许把失败当成合规。
- **语义去重留作增强**：若联调发现不同措辞描述同一风险、代码去重对不上，再评估是否建 LLM 合并工作流（届时补 DSL）。

---

## 6. 应用四：规章制度生成（Workflow）

### 6.1 定位

两段式：先按需求生成**大纲**，用户确认后再生**全文**。用 `mode` 区分两段，一个工作流内部条件分支。DSL 见 `dify/dsl/规章制度生成.yml`。

**生成后自动做合规审查**：后端拿到全文章节后，逐块调用「制度审查」应用做冲突检测；若不合规，把冲突清单与上一版全文回传本工作流**重新生成（修正模式）**，最多自动修正 3 轮。审查逻辑不重复实现——复用应用三。

### 6.2 节点编排

```
开始(Start：requirement, mode, outline, previous_sections, review_conflicts, revision_round)
  → 知识检索（法律法规 + 现行制度，2 库，作为写作参照）
  → 条件分支(IF mode == "outline")
      ├─ 大纲 → LLM 生成大纲 → Code 规整 → 聚合器
      └─ 全文 → LLM 撰写/修正全文 JSON → Code 兜底解析 → 聚合器
  → 结束(End：mode, outline_text, sections_json)
```

> 生成阶段就挂「法规 + 现行制度」检索，让模型写作时参照上位依据，**从源头降低后续审查发现的冲突率**。

### 6.3 输入变量（Start 节点定义）

| 变量 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `requirement` | paragraph | 是 | 用户的内容需求描述 |
| `mode` | select | 是 | `outline`（生成大纲）/ `document`（生成全文） |
| `outline` | paragraph | 否 | `mode=document` 时传入用户确认后的大纲 |
| `previous_sections` | paragraph | 否 | 上一版全文（修正轮次传入，首次生成为空） |
| `review_conflicts` | paragraph | 否 | 上一轮审查的冲突清单 JSON（修正轮次传入） |
| `revision_round` | number | 否 | 修正轮次（后端控制，1 起，最多 3） |

### 6.4 输出

- `mode`：回显模式，后端据此决定取哪个字段。
- `mode=outline`：输出 `outline_text`（可编辑的大纲文本），`sections_json` 为空。
- `mode=document`：输出 `sections_json`（`{"sections": [{"title": "...", "content": "..."}]}`），后端用 `python-docx` 排版成 `.docx`。
- 两个 End 分支输出同构（都含 mode / outline_text / sections_json），后端无需分支解析。

### 6.5 Prompt 要点

- **大纲分支**：按「章—条」层级输出大纲，覆盖需求全部事项，不与现行制度/上位法冲突；只输出大纲文本（Markdown 标题层级）。
- **全文分支**：内含「生成模式判定」——`previous_sections` 为空走**首次撰写**（按大纲逐章写全）；非空走**修正模式**（以上一版全文为基准，仅逐条修正冲突清单指出的问题，其余保持不变，不新增无关章节、不删减内容）。输出固定 JSON schema，引用依据必须来自检索参考资料，不得编造。

### 6.6 自动合规审查与修正循环（后端编排，最多 3 轮）

```
sections = 生成(requirement, outline)                    # 第 1 次生成
round = 0
while True:
    review = 切块逐块调「制度审查」应用 → 合并去重         # 见应用三
    if review.is_compliant or round >= 3: break
    round += 1
    sections = 生成(requirement, outline,
                    previous_sections=上一版全文,
                    review_conflicts=合并去重后的冲突清单,
                    revision_round=round)
返回: sections + 最后一轮 review（含 max_rounds_reached 标记）
```

要点：

1. **循环在后端，Dify 只做单轮生成**：切块、进度、循环控制在后端，符合「长文档块级控制留在后端」的既定原则。
2. **修正基于上一版全文**：只回传冲突清单而不给上一版全文，模型会整篇重写，可能引入新冲突导致循环不收敛；给了全文才能最小化改动。
3. **回传前先合并去重**：逐块审查会产出大量重复/碎片冲突，直接回传噪音太大；先合并去重、按风险等级排序、截断到合理条数（建议 ≤15 条）再回传。
4. **修正建议不单独审**：审查范围为生成的正文全文；`requirement` 是需求描述、不是制度条文，不纳入冲突检测。
5. **成本上限**：最多 3 轮修正，即最多 4 次全套审查；若第 3 轮仍不合规，标记 `max_rounds_reached=true` 返回，提示人工复核。
6. **过程留痕**：每轮的全文章节与审查结果都落库，供追溯与专家纠错（需求⑤）。

---

## 7. API Key 与后端 `.env` 映射

在 Dify 每个应用「API 访问」里生成 API Secret，填入后端 `backend/.env`：

| `.env` 变量 | Dify 应用 |
| --- | --- |
| `DIFY_BASE_URL` | Dify 服务地址（docker-compose 内服务名，如 `http://dify-api`） |
| `DIFY_CHAT_APP_KEY` | 合规咨询（Chatflow） |
| `DIFY_CONTRACT_REVIEW_APP_KEY` | 合同审查（Workflow） |
| `DIFY_REGULATION_REVIEW_APP_KEY` | 制度审查（Workflow） |
| `DIFY_GENERATE_APP_KEY` | 规章制度生成（Workflow） |

> 后端 `config.py` / `.env.example` 现有的 `DIFY_REVIEW_APP_KEY` 需同步拆分为上述两个变量（后端改造时落实）。

**新增知识库 dataset_id 配置（后端 `config.py` + `.env` 需补充）**：

| `.env` 变量 | 知识库 |
| --- | --- |
| `DATASET_ID_LAW` | 法律法规库 |
| `DATASET_ID_REGULATION` | 某钢规章制度库 |
| `DATASET_ID_CASE` | 典型案例库 |
| `DATASET_ID_RULE` | 审核规则库 |
| `DATASET_ID_EXPERT` | 专家知识库 |

---

## 8. 构建顺序与验证清单

### 8.1 建议构建顺序

1. **先建 5 个知识库**（含空的专家知识库），记下 dataset_id。
2. 导入 **合同审查 Workflow**，上传含多段条款的文件，检查提取、切块、逐块报告和后端校验。
3. 导入独立的 **制度审查 Workflow**。
4. 建 **合规咨询 Chatflow**（挂 2 库，测多轮问答与引用）。
5. 建 **规章制度生成 Workflow**（测 outline / document 两段；再联调「生成 → 自动审查 → 修正重生成」循环）。
6. 审查合并不建 Dify 应用，由后端按第 5 节规则实现。

### 8.2 每个应用发布后验证

- 合同审查：上传合规和含风险的多段文件，确认 `chunks` / `results` 等长、逐块引用可核对，后端标记无法核对的风险。
- 制度审查：同上；`reference_case` 恒为 null。
- 合规咨询：连续多轮提问，确认回答带引用来源，且能按 `category` 切换语境。
- 规章制度生成：先 `mode=outline` 得大纲，再 `mode=document` + 大纲得全文 JSON；修正模式用 `previous_sections` + `review_conflicts` 验证只改动被指出的部分。
- 记录每个应用生成 API Key，同步填 `.env`，再用后端 `chat_stream`/`run_workflow` 联调。

---

## 9. 与后端衔接要点（预告）

- 后端 `services/dify.py` 已封装 `chat` / `chat_stream` / `run_workflow` / `run_workflow_stream` / `upload_document` / `create_document_by_text`，与上述 4 个应用的接口一一对应。
- 合同审查：后端上传文件后通过 `run_workflow_stream` 传 `input_file`；Dify 提取、切块和逐块审查，后端校验并合并。制度审查：后端解析切块后逐块调用 `run_workflow`，输入为 `chunk_text`。
- 合规咨询：后端 `chat_stream` 传 `query/category`，SSE 转发到前端。
- 规章制度生成：后端 `run_workflow` 传 `requirement/mode/outline`（修正轮次另传 `previous_sections/review_conflicts/revision_round`）；生成后后端切块调「制度审查」应用，不合规则自动修正重生成，最多 3 轮。
- 后端接口细节见 `功能实现策略.md` 各模块章节，后续进入「后端程序接口对应」阶段再展开。
