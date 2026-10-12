# dify/ — Dify 应用与工作流版本管理

本目录存放 RAG_demo 平台所有 Dify 应用的 DSL 导出文件与部署说明。应用设计详见 `docs/Dify应用与工作流设计.md`。

## 应用清单

| 应用 | 类型 | DSL 文件 | 状态 |
| --- | --- | --- | --- |
| 合同审查（需求②） | Workflow | `dsl/合同审查.yml` | ✅ 已导入联调；Dify 提取、切块、迭代审查 |
| 制度审查（需求③） | Workflow | `dsl/制度审查.yml` | ✅ 已定稿 · 已联调 |
| 合规咨询（需求④） | Chatflow | `dsl/合规咨询.yml` | ✅ 已定稿 · 已联调 |
| 规章制度生成（需求⑧） | Workflow | `dsl/规章制度生成.yml` | ✅ 已定稿 · 已联调 |
| 合同模板结构化（需求⑥） | Workflow | `dsl/合同模板结构化.yml` | ✅ 已定稿 · 已联调 |
| 审查汇总（②③长文档） | — | 无（后端代码实现合并去重） | ❌ 不建 |

### 联调状态（2026-09-13 验证）

合同审查的新工作流已在 Dify 验证。下表保留其他应用此前的联调记录；可用冒烟脚本复测：

```bash
cd backend && .venv/bin/python ../dify/scripts/smoke_test.py
```

| 应用 | 实测结果 |
| --- | --- |
| 制度审查 | 6.1s，`is_compliant=false`，2 条冲突（含与现行制度条款的冲突） |
| 合规咨询 | 3.2s，回答 388 字，引用来源 3 条 |
| 规章制度生成 | 5.6s，大纲 1628 字，`sections_json` 正确为空（outline 模式） |

---

## DSL 格式规范（Dify 1.17.0）

> 本节记录一次真实踩坑：手写 DSL 导入后画布显示异常。原因是写成了一般化的 Dify DSL 教程格式，而非 Dify 1.17 的真实导出格式。**新建/修改 DSL 时必须遵守以下约定。**

| 项 | 正确写法 | 常见错误 |
| --- | --- | --- |
| 节点 ReactFlow 类型 | 顶层 `type: custom`，语义类型放 `data.type`（`start` / `llm` / `code` / `if-else` / `variable-aggregator` / `end` / `knowledge-retrieval`） | 顶层写 `type: llm` 且 `data` 里无 `type` → 前端找不到渲染组件，节点显示异常 |
| 顶层元数据 | `kind: app`、`dependencies: []`、`version: 0.3.1` | `kind: app-kind`；缺 `dependencies` |
| 版本兼容 | Dify 1.17 当前 DSL 版本为 `0.7.0`；声明 `0.3.1` 会以「有警告」状态导入（**无迁移机制**，图结构必须本身就是正确的） | 以为声明旧版本会自动升级结构 |
| 节点通用字段 | `data` 内含 `desc` / `selected` / `title` / `type`；节点级含 `selected` | 缺 `selected`/`desc` |
| 变量聚合器 | `variables: [[node_id, output], ...]`（二元数组列表）、`output_type`、`advanced_settings: {group_enabled: false, groups: []}` | 写成 `variables: [{variable, value_selector}]` 字典列表 |
| End 输出 | `outputs: [{variable, value_selector, value_type}]` | 缺 `value_type` |
| Code 节点 | 字段名为 `code_language: python3`；`outputs: {变量: {children: null, type: string}}` | 多写非标准 `language` 字段 |
| LLM 节点 | 需含 `context` / `vision` / `memory` / `structured_output` / `retry_config` | 只写 `model` + `prompt_template` |
| if-else 条件 | `comparison_operator: is`（字符串相等）、`varType: string`；分支边 `sourceHandle` 取 `'true'` / `'false'` | — |

**校验（改完 DSL 必跑）**：

```bash
bash dify/scripts/validate.sh          # 默认容器 docker-api-1
```

脚本用 Dify 容器内**自身的 pydantic 节点模型**逐节点校验，能发现上面所有问题。

> **补充（技能已升级）**：`dify/dify-workflow-builder/` 是 dify-workflow-builder 技能的完整副本，
> 已按 Dify 1.17 真实导出格式重写。它的 `scripts/validate_dsl.py` + `validate.sh` 同样是
> **在容器内用 Dify 自身的 pydantic 节点模型**逐节点校验（等价于本项目的 `dify/scripts/validate.sh`），
> 并额外做信封/语法层检查（顶层 `type: custom`、`kind: app`、边的 handle、变量引用解析、
> 环境变量用 `name` 而非 `variable`、聚合器二元数组、密钥扫描、不可达节点告警等）。
> 早先「技能自带校验器对 1.17 会误报」的结论已不成立。
>
> 新建 DSL 时可直接用该技能：`templates/` 下 9 个模板与 `examples/` 下 3 个示例均通过校验，
> 可用 `scripts/generate_dsl.py` 复制改写，用 `scripts/dify_dsl.py` 组合新图，用
> `render_flow.py` 出流程图。踩坑清单见 `dify/dify-workflow-builder/references/pitfalls.md`。
> 本项目自身的 `dify/scripts/validate.sh` 仍然有效，两者可互为交叉验证。

---

## 合同审查 Workflow

部署 `dsl/合同审查.yml`。工作流顺序：`Start(input_file)` → 文档提取器 → Code 按段落切块（约 2000 字）→ Iteration 对每块分别检索法规、制度和典型案例 → Qwen 一次生成结构化报告 → Code 封装该块原文、报告及三路检索原始结果 → End 返回 `chunks` 和 `results` 两个等长数组。

后端仅上传文件、接收工作流结果、校验风险原文与本次法规/制度检索证据、合并风险并保存任务。文本输入写入临时 `.txt` 后同样交给 Dify；旧式 `.doc` 在上传前转换为 `.docx`。制度审查仍使用原有后端解析与切块。

部署步骤：

1. 在 Dify 导入并发布 `dsl/合同审查.yml`，检查文档提取器、切块 Code 和 Iteration 的连接。
2. 确认三路检索节点依次绑定法规库、制度库、典型案例库，并配置 Qwen 模型及 rerank 模型。
3. 将该应用的 API Secret 写入后端 `DIFY_CONTRACT_REVIEW_APP_KEY`。
4. 上传一份多段合同，核对 End 的 `chunks` 与 `results` 数量相同，逐块风险原文能在对应 `chunks[i]` 中找到；再通过后端查看校验与汇总结果。

已在 Dify 实例验证文档提取、切块和逐块审查。部署到新实例时仍需检查知识库、模型与应用 API Secret 的绑定。

---

## 制度审查 Workflow

### 编排

制度审查沿用原有两段式判定、分支、聚合器和单 End，关键配置：

- 知识检索只挂 **2 库**：法律法规库、某钢规章制度库（无案例/审核规则/专家标注），Top K 5。
- LLM-1 判定语义为**冲突检测**：是否与上位法/现行制度冲突、越权或矛盾；文字表述/格式问题不算不合规。
- LLM-2 输出**无 `reference_case` 字段**，`violations`（law_name/article/description）与合同审查同名同构，`suggestion` 依据被冲突的上位条款给出。
- Code 节点兜底逻辑相同（解析失败按不合规处理）。

### 变量表

Start 接收后端传入的 `chunk_text`；End 返回 `is_compliant`、`compliance_reason`、`risks` 和 `parse_error`。

**End 输出**：

```json
{
  "is_compliant": "true 或 false（字符串）",
  "compliance_reason": "合规：判定依据 / 不合规：冲突条数摘要",
  "risks": [ { "clause": "...", "risk_level": "...", "violations": [{"law_name": "《法规/制度名》", "article": "...", "description": "冲突说明"}], "suggestion": "..." } ]
}
```

### 部署步骤

1. 导入 `dsl/制度审查.yml`。
2. 「知识检索」节点绑定 2 个知识库：**法律法规库、某钢规章制度库**。
3. 确认 DeepSeek 供应商已配置；发布后生成 API Secret → 填入 `DIFY_REGULATION_REVIEW_APP_KEY`。

### 验证用例

- **无冲突文本**：输入一段与上位依据不冲突的制度条文 → 期望 `is_compliant="true"`、`risks=[]`。
- **冲突文本**：输入与检索到的现行制度/法规明显矛盾的条款（如权限、审批层级、限额冲突）→ 期望 `is_compliant="false"`，`risks[].violations` 列明具体冲突的法规/制度名称与条款号。
- **编辑问题过滤**：输入仅有错别字/格式问题的文本 → 期望判定为合规（不把编辑问题当合规问题）。

---

## 合规咨询 Chatflow

### 编排

```
Start(category)
  → LLM 问题改写（带对话记忆）
  → Code 改写兜底（空/超长 → 回退 sys.query）
  → 知识检索（某钢规章制度库 + 专家知识库，Top K 3）
  → LLM 回答（对话记忆 + category 语境 + 检索上下文）
  → Answer
```

> Chatflow 的终止节点是 `answer`；与 Workflow 不同，这里不用 `end`。

### 变量表

| 变量 | 类型 | 来源 | 消费节点 |
| --- | --- | --- | --- |
| `category` | select（差旅/接待/招采/通用） | Start 表单变量（前端选择、后端透传 `inputs`） | LLM 回答 prompt |
| `sys.query` | string | 系统变量（Dify 自动提供） | LLM 问题改写、改写兜底（original）、LLM 回答 |
| `text` | string | LLM 问题改写输出 | 改写兜底 |
| `question` | string | code_rewrite 输出 | 知识检索（query） |
| `result` | array[object] | 知识检索输出 | LLM 回答 context（`{{#context#}}`） |
| `conversation_id` | string | Dify 自动管理 | 多轮上下文（后端透传即可） |

### 部署步骤

1. 导入 `dsl/合规咨询.yml`（应用类型为 Chatflow / advanced-chat）。
2. 「知识检索」节点绑定 2 个知识库：**某钢规章制度库、专家知识库**。
3. 确认 DeepSeek 供应商已配置。
4. 确认 `features.retriever_resource.enabled = true`（引用来源卡片依赖它，勿关闭）。
5. 发布后生成 API Secret → 填入 `DIFY_CHAT_APP_KEY`。

### 验证用例

- **单轮提问**：`category=差旅`，问「差旅住宿标准是多少？」→ 期望依据制度库作答，回答末尾有依据来源，`metadata.retriever_resources` 非空。
- **多轮追问**：先问「差旅住宿标准是多少？」，再追问「那接待呢？」→ 期望改写节点把追问补全为「某钢集团业务接待标准/费用上限是多少」，检索召回正确，而不是拿「那接待呢」去检索。
- **知识库外问题**：问一个制度库里没有的问题 → 期望回答「知识库中暂无相关内容」，不臆造。
- **纠错闭环**：在专家知识库写入一条纠错内容 → 重新提问相关问题 → 期望回答参考该内容（需求⑤闭环）。

---

## 规章制度生成 Workflow

### 编排

```
Start(requirement, mode, outline, previous_sections, review_conflicts, revision_round)
  → 知识检索（法律法规 + 现行制度，2 库，写作参照，Top K 5）
  → IF mode == "outline"
      ├─ 大纲 → LLM 生成大纲 → Code 规整 → 聚合器
      └─ 全文 → LLM 撰写/修正全文 JSON → Code 兜底解析 → 聚合器
  → End(mode, outline_text, sections_json)
```

### 变量表

| 变量 | 类型 | 来源 | 说明 |
| --- | --- | --- | --- |
| `requirement` | paragraph | 后端 `inputs` | 起草需求（必填） |
| `mode` | select | 后端 `inputs` | `outline` / `document`（必填） |
| `outline` | paragraph | 后端 `inputs` | 用户确认后的大纲（document 模式传） |
| `previous_sections` | paragraph | 后端 `inputs` | 上一版全文；**为空=首次撰写，非空=修正模式** |
| `review_conflicts` | paragraph | 后端 `inputs` | 上一轮合并去重后的冲突清单 JSON |
| `revision_round` | number | 后端 `inputs` | 修正轮次（1 起，最多 3） |
| `outline_text` | string | 聚合器输出 | mode=outline 时的大纲文本 |
| `sections_json` | string | 聚合器输出 | mode=document 时的 `{"sections":[{"title","content"}]}` |

### 自动合规审查 + 修正循环（后端实现，不在本工作流内）

```
sections = run_workflow(mode=document)                # 第 1 次生成
round = 0
while True:
    review = 切块调用「制度审查」应用 → 合并去重        # 复用应用三
    if review.is_compliant or round >= 3: break
    round += 1
    sections = run_workflow(mode=document, outline=...,
                            previous_sections=上一版全文,
                            review_conflicts=合并去重后的清单(≤15 条),
                            revision_round=round)
```

- **循环在后端**，Dify 只做单轮生成，便于报进度（「第 i 轮修正 / 第 j 块审查」）。
- **修正必须带 `previous_sections`**：只给冲突清单会让模型整篇重写，可能引入新冲突导致循环不收敛。
- 最多修正 3 轮（即最多 4 次全套审查）；第 3 轮仍不合规则返回并标记 `max_rounds_reached`，提示人工复核。
- 审查范围＝生成的正文全文；`requirement` 是需求描述，不纳入冲突检测。

### 部署步骤

1. 导入 `dsl/规章制度生成.yml`。
2. 「知识检索」节点绑定 2 个知识库：**法律法规库、某钢规章制度库**。
3. 确认 DeepSeek 供应商已配置。
4. 发布后生成 API Secret → 填入 `DIFY_GENERATE_APP_KEY`。
5. 自动审查依赖「制度审查」应用，需同时部署并配置 `DIFY_REGULATION_REVIEW_APP_KEY`。

### 验证用例

- **大纲**：`mode=outline` + 需求 → 期望返回 Markdown 层级大纲，覆盖需求全部事项，`sections_json` 为空。
- **首次全文**：`mode=document` + 大纲（`previous_sections` 留空）→ 期望 `sections_json` 为合法 JSON 且章节齐全。
- **修正模式**：`previous_sections` = 上一版全文、`review_conflicts` = 一条真实冲突 → 期望仅相关条款被修改，其余内容与上一版基本一致，且不再触发同一冲突。
- **兜底解析**：令 LLM 输出非 JSON → 期望降级为单章节 + `parse_error="true"`，仍能落盘。

---

## 合同模板结构化 Workflow/Agent

> 对应需求⑥（合同模板库）：模板导入时智能识别待填字段。后端先把 `.docx` 扫描成「带锚点的文档结构大纲」+「候选空位清单」+「字段槽位清单」，交给本应用输出结构化字段清单 JSON，前端据此生成填充表单，后端据此渲染 docxtpl 占位符。

### 编排

```
Start(doc_outline, candidates_json, slots_json, template_name)
  → LLM 识别待填字段（通读大纲 + 槽位清单，temperature 0.1 / response_format=json_object）
  → Code 兜底解析与规整（剥 <think> → 从后往前取含 fields 的最后一个合法 JSON → 绑槽位、规整 key/type/anchor）
  → End(fields_json, parse_error)
```

共 **4 节点 / 3 边**（`start` / `llm` / `code` / `end`），单链路无分支、无聚合器。

### 变量表

| 变量 | 方向 | 类型 | 说明 |
| --- | --- | --- | --- |
| `doc_outline` | Start 输入 | paragraph | 带锚点编号的文档结构文本，如 `[p0] 钢材采购合同` / `[p1] 甲方（采购方）：__________`（必填） |
| `candidates_json` | Start 输入 | paragraph | 后端规则扫描出的候选空位清单 JSON 字符串，可为 `[]` |
| `slots_json` | Start 输入 | paragraph | **字段槽位清单** JSON 字符串：同名变量已合并成一个槽位，是模型识别的判断单位，可为 `[]` |
| `template_name` | Start 输入 | paragraph | 模板名称（必填） |
| `llm_output` | LLM 输出 | string | 模型原始输出（仅内部，供 Code 解析） |
| `fields_json` | Code 输出 | string | 字段清单 JSON 字符串 |
| `parse_error` | Code 输出 | string | `"true"` / `"false"`；后端据此把本次识别标记为失败并提示人工复核 |

> `slots_json` 是后加的入参，用于识别 Word 表单域（FORMTEXT）与 `#...#` 占位符、并让同名变量只填一次。它对模型是可选的：老版本后端不传时，模型退化成只按大纲 + 候选清单判断。`candidates_json` 仍然保留，供字段回找原始锚点。

**End 输出**（后端 `run_workflow` 的 `outputs`）：

```json
{
  "fields_json": "{\"contract_type\":\"采购\",\"fields\":[{\"key\":\"PUR_BILL_TO_NAME\",\"label\":\"甲方单位名称\",\"type\":\"text\",\"required\":true,\"slot_id\":\"s2\",\"owner\":\"甲方\",\"source_name\":\"PUR_BILL_TO_NAME\",\"anchor\":\"p3\",\"default\":\"\",\"options\":[],\"confidence\":0.96,\"reason\":\"模板表单域名为 PUR_BILL_TO_NAME，位于『甲方：』之后\"}],\"ignored\":[{\"slot_id\":\"s30\",\"anchor\":\"\",\"reason\":\"已有固定条款正文\"}],\"notes\":\"识别到 37 个待填字段\"}",
  "parse_error": "false"
}
```

**Code 节点的硬约束（后端依赖，不可放宽）**：

- `key` 必须是合法 Jinja 标识符 `^[A-Za-z_][A-Za-z0-9_]*$`（英文/拼音+下划线）；模型若输出中文/空格键，Code 先退回槽位原名，再退回 `field_N`，保证不产生非法占位符。
- **带 `name` 的槽位（表单域 / `#...#`），`key` 必须原样沿用 `name`**：`PUR_BILL_TO_NAME`、`DTK9980` 这类名字来自甲方既有模板体系，改写会让生成的合同对不上他们的数据字段。只有 `#...#` 的内文是中文时（不符合标识符规则）才另起英文 key，中文原名进 `label`。
- **一个槽位一个字段**；`slot_id` 必须原样照抄 `slots_json`，集合外的 `slot_id` 会被置空（后端退回按原名/锚点定位）。
- `type` 只能取 `text` / `textarea` / `date` / `number` / `select`；别名（如 `string`/`enum`）会被归一化，`select` 无 `options` 时自动降为 `text`。
- `anchor` 必须来自输入：Code 从 `doc_outline` 的 `[pN]` 与 `candidates_json` 中收集合法锚点集合，集合外的锚点置空，杜绝编造。
- `owner` 取「甲方」「乙方」「附件」之一；后端给的 `owner_hint` 只是提示（同时提到甲乙双方的条款里容易误判），以模型自己的判断为准。**`label` 必须全局唯一**——甲乙双方成对的字段（「联系地址」「开户银行」「账号」「社会信用代码」「单位名称」）原文标签一模一样，要靠 `owner` 补成「甲方联系地址」「乙方联系地址」这类可区分的名字。

### 关于 Agent 节点降级为 LLM 节点

用户要求用 Agent 节点承担识别。本机 Dify 1.17.0 容器内**确实存在** Agent 节点模型（`core/workflow/nodes/agent/entities.py::AgentNodeData`，`data.type = "agent"`），但其 DSL 字段结构（`agent_strategy_*` / `agent_parameters` / 插件 `plugin_unique_identifier` 等）与项目现有 4 个 DSL 差异较大，且依赖由插件提供的 agent 策略（当前环境无法确认已安装可用策略），硬写 Agent 节点导入后会成为坏节点。项目校验脚本 `dify/scripts/validate_dsl.py` 原先**只注册了 8 种节点模型、未注册 `agent`**，含 Agent 节点的 DSL 必然报 `FAIL 节点 xxx: 未知 data.type: agent`——该缺口已修复（`agent` 已注册，并注明其插件依赖），后续可随时切回 Agent 节点。

> **联调结论（2026-09-14）**：LLM 节点形态已实测通过。对一份纯下划线填空、不含任何 `{{ }}` 的合同模板，2 秒返回 5 个字段（含中文标签、控件类型、必填标记、置信度与判断理由），并正确忽略标题与固定条款；下游"复核确认 → 必填拦截 → 生成 → 产物校验"全链路通过。
> **注意**：提示词要求输出 `slot_id`（含 `name` 的槽位还要原样沿用 `name` 做 key），比早期只输出 `anchor` 精确得多——同一段落里多个变量（实测通知条款 8 个、生效期限 9 个）靠 `slot_id` 才能各自定位。旧版应用只给 `anchor` 时后端仍按锚点回退解析，不会因为没重新导入应用就整条链路不可用。

因此按任务约定「校验无法通过则降级」，本应用**使用 LLM 节点承载识别**，输入输出契约与 Agent 方案完全一致（同为 4 入 2 出）。若后续 `validate_dsl.py` 补充 `agent` 节点模型，可直接把 `llm_struct` 节点替换为 Agent 节点（`agent_strategy_provider_name: langgenius/agent/agent` + `agent_strategy_name: function_calling`），Code / End 节点无需改动。

### 模型与参数

`name: deepseek-v4-flash`、`thinking: false`、`temperature: 0.1`、`max_tokens: 4096`、`response_format: json_object`（`structured_output` 保持关闭，沿用项目既有 JSON 约束方式）。

### 部署步骤

1. Dify 控制台 → 创建应用 → **导入 DSL 文件** → 选择 `dsl/合同模板结构化.yml`。
2. 确认 DeepSeek 供应商已配置 API Key（LLM 节点模型为 `deepseek-v4-flash`，思考模式已关闭）。
3. 本应用**不检索知识库**，无需绑定任何 dataset（`context.enabled = false`）。
4. 发布应用 → 「API 访问」生成 API Secret → 填入后端 `backend/.env` 的 `DIFY_TEMPLATE_STRUCTURE_APP_KEY`。
5. 后端上传 `.docx` 后：扫描空位与槽位 → 拼装 `doc_outline` / `candidates_json` / `slots_json` / `template_name` → 调用本应用 → 用 `fields_json` 生成填充表单与 docxtpl 占位符；`parse_error="true"` 时提示人工复核。

> **改了提示词/Code 节点后必须重新导入本应用**（Dify 不会自动同步仓库里的 DSL）。旧应用仍能跑（`slots_json` 可选、后端有锚点回退），但识别不到表单域与 `#...#`，且同一段落多个变量会定位不准。

### 验证用例

- **纯下划线填空模板**：`doc_outline` 含 `[p1] 甲方（采购方）：__________`、`[p2] 乙方（供货方）：__________`、`[p9] 签订日期：____年__月__日` → 期望 `fields` 覆盖甲乙方名称与签订日期，日期字段 `type="date"`，各 `anchor` 正确指向 p1/p2/p9。
- **Word 表单域模板**：`slots_json` 含 `{"slot_id":"s2","kind":"form_field","name":"PUR_BILL_TO_NAME","label_hint":"甲方","owner_hint":"甲方","occurrences":2}` → 期望该字段 `key` 原样为 `PUR_BILL_TO_NAME`（不得改写成小写）、`slot_id="s2"`、`label` 是中文业务名（如「甲方单位名称」）而非 `label_hint` 原文。
- **`#...#` 占位符模板**：`slots_json` 含 `{"slot_id":"s46","kind":"hash","name":"供应商名称"}` → 期望 `key` 是英文（如 `supplier_name_att`）、`label` 含中文原名，`slot_id` 照抄。
- **同名标签消歧**：`slots_json` 同时含 `REGIST_ADDR`（owner_hint=甲方）与 `SUPPLIER_ADDR`（owner_hint=乙方），两者 `label_hint` 都是「联系地址」→ 期望两条 `label` 分别补成「甲方联系地址」「乙方联系地址」，不得输出两个同名 label。
- **无占位符模板**：`doc_outline` 全为固定条款正文（如「第一条 本协议自双方签字之日起生效」），`candidates_json="[]"`、`slots_json="[]"` → 期望 `fields=[]`、`parse_error="false"`、`notes` 说明无需填写字段（不臆造字段）。
- **候选误报**：`slots_json` 混入一条实为固定条款的槽位 → 期望该条进入 `ignored` 并给出原因，不出现在 `fields`。
- **非法键/锚点兜底**：令模型故意返回中文 `key` 与不存在的 `anchor` → 期望 `key` 退回槽位原名（没有 name 时才是 `field_N`）、`anchor` 置空，输出仍是合法 JSON。
- **兜底解析**：令模型输出非 JSON（如「抱歉，我无法完成」）→ 期望 `parse_error="true"`、`fields=[]`，流程不报错。

### 校验

```bash
bash dify/scripts/validate.sh
```

实测结果：本应用 `节点数: 4 | 边数: 3 | start: 1 | end: 1`，与既有 4 个应用一并**全部通过**（exit 0）。
