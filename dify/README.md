# dify/ — Dify 应用与工作流版本管理

本目录存放 RAG_demo 平台所有 Dify 应用的 DSL 导出文件与部署说明。应用设计详见 `docs/Dify应用与工作流设计.md`。

## 应用清单

| 应用 | 类型 | DSL 文件 | 状态 |
| --- | --- | --- | --- |
| 合同审查（需求②） | Workflow | `dsl/合同审查.yml` | ✅ 已定稿 · 已联调 |
| 制度审查（需求③） | Workflow | `dsl/制度审查.yml` | ✅ 已定稿 · 已联调 |
| 合规咨询（需求④） | Chatflow | `dsl/合规咨询.yml` | ✅ 已定稿 · 已联调 |
| 规章制度生成（需求⑧） | Workflow | `dsl/规章制度生成.yml` | ✅ 已定稿 · 已联调 |
| 审查汇总（②③长文档） | — | 无（后端代码实现合并去重） | ❌ 不建 |

### 联调状态（2026-09-13 验证）

四个应用均已导入 Dify 1.17.0 并联调通过，可用冒烟脚本随时复测：

```bash
cd backend && .venv/bin/python ../dify/scripts/smoke_test.py
```

| 应用 | 实测结果 |
| --- | --- |
| 合同审查 | 4.8s，`is_compliant=false`，2 条风险，依据《民法典》第五百零六条等 |
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
| 变量聚合器取值顺序 | 聚合器取列表中**第一个「非空值」**，而 `[]` 空数组也算非空。因此**分支专属的来源必须排在「分支前必然执行」的节点之前** | 合同审查曾把 `code_judge.risks`（分支前执行、恒为 `[]`）排在前，导致不合规分支识别出的真实风险被空数组覆盖，返回 `risks=[]` |

**校验（改完 DSL 必跑）**：

```bash
bash dify/scripts/validate.sh          # 默认容器 docker-api-1
```

脚本用 Dify 容器内**自身的 pydantic 节点模型**逐节点校验，能发现上面所有问题。注意：dify-workflow-builder 技能自带的 `scripts/validate_dsl.py` 校验的是它自己的简化格式（要求顶层 `type: start`），**对 Dify 1.17 的真实格式会误报**，本项目以 `dify/scripts/validate.sh` 为准。

---

## 模型与参数约定（DeepSeek 插件 0.0.24）

> 本节记录一次真实踩坑。首次联调时合同审查返回「判定结果解析失败」、`risks` 为空，排查结论如下。

### 1. 模型名必须用插件声明的名字

插件 0.0.24 声明的模型只有：`deepseek-flash`、`deepseek-v4-flash`、`deepseek-v4-flash-vision-exp`、`deepseek-v4-pro`。

**`deepseek-chat` 不在清单中**，而插件对未声明的模型名不做任何参数归一化、直接透传上游——结果：

- `thinking` 参数被静默忽略，**思考模式默认开启**（judge 单次 4440 completion tokens、28 秒）；
- 思维链被输出到 `llm.text` 里（`<think>…</think>` + `<!--dify-deepseek-reasoning-->` 标记），把 JSON 答案淹没了。

### 2. 节点参数约定（已写入 4 个 DSL）

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `name` | `deepseek-v4-flash` | 插件声明的模型；质量不够时可换 `deepseek-v4-pro`（UI 下拉选择） |
| `thinking` | `false` | 关思考模式。**必须关**：开启时延迟/成本高一个数量级，且思维链会污染输出 |
| `response_format` | `json_object` | 仅对输出 JSON 的节点（判定 / 违规分析 / 冲突标注 / 全文生成）设置 |
| `temperature` | 判定 0.1、分析 0.2、改写 0.1、问答 0.3 | 关闭思考模式后该参数才生效（插件在思考模式下会丢弃 temperature） |
| `max_tokens` | 判定 1024 / 分析 **8192** / 全文 8192 / 改写 256 / 问答 2048 | 防跑飞；全文生成给足额度 |

### 3.1 违规分析输出被截断（已修，需重新导入两个审查应用）

联调中发现的严重问题：**块较大（约 2800 字以上）时，违规分析节点的 JSON 输出会超出 `max_tokens=4096`
被截断（`finish_reason=length`），解析兜底返回空风险列表，整块被静默判为「无风险」**——
合规场景下的危险假阴性（判定环节其实已正确识别出违反《民法典》第五百零六条）。

修复三件套：

1. 违规分析 / 冲突标注节点的 `max_tokens` 提到 **8192**；
2. prompt 增加篇幅约束（description ≤60 字、violations ≤3 条、最多 10 条风险、必须输出完整合法 JSON）；
3. **End 输出透出 `parse_error`**（新增「合并解析标志」聚合器），后端据此把解析失败的块计为失败块并提示人工复核。

> 因此 `dsl/合同审查.yml`、`dsl/制度审查.yml` 已更新为 **11 节点 / 15 边**，
> 需重新导入这 2 个应用（其余 2 个应用未改动，无需重导）。
> 后端的安全网（判定不合规但无风险明细也算失败块）已生效，即使暂不重导也不会再出现静默假阴性。

### 3. Code 节点必须能容忍思考链

即使关闭了思考模式，解析器仍按「容忍思考链」实现（防御性）：先剥离 `<think>…</think>`，再**从后往前**逐个候选花括号对象尝试解析，取**最后一个含目标键的合法 JSON**（即最终答案，而非思维链里的示例）。这样才能避免「首个 `{` 到最后一个 `}`」把思考内容圈进来的经典错误。

### 4. 检索已开启 Rerank

三方模型里已配置 SiliconFlow 的 `BAAI/bge-reranker-v2-m3`，合同审查 / 制度审查 / 规章制度生成的检索节点已开启 `reranking_enable: true`（首次联调时检索命中质量差，Top 1 得分为 0.03，命中内容与待审条款无关）。

---



## 合同审查 Workflow

### 编排

```
Start(chunk_text)
  → 知识检索（法规 + 制度 + 典型案例，3 库，Top K 5）
  → LLM-1 合规判定（DeepSeek，temperature 0.1）
  → Code 解析判定结果（JSON 兜底，失败按不合规处理）
  → IF is_compliant == "true"
      ├─ 合规   → 聚合器（reason / risks=[]）→ End
      └─ 不合规 → LLM-2 违规分析（temperature 0.2）
                → Code 兜底解析 → 聚合器 → End
```

> Dify 校验器要求恰好一个 End 节点，因此两分支经两个变量聚合器（`compliance_reason` / `risks`）汇到同一 End，输出结构与设计文档 3.8 节一致。

### 变量表

| 变量 | 类型 | 来源 | 消费节点 |
| --- | --- | --- | --- |
| `chunk_text` | paragraph | Start 输入（后端切块传入） | 知识检索（query）、LLM-1、LLM-2 |
| `result` | array[object] | 知识检索输出 | LLM-1 / LLM-2 的 context（`{{#context#}}`） |
| `text` | string | LLM-1 / LLM-2 输出 | Code 解析节点 |
| `is_compliant` | string（"true"/"false"） | code_judge 输出 | 条件分支、End 输出 |
| `reason` | string | code_judge 输出 | agg_reason（合规分支）、End |
| `risks` | array[object] | code_judge（恒 `[]`）/ code_parse 输出 | agg_risks、End |
| `summary` / `parse_error` | string | code_parse 输出 | agg_reason / 调试 |

**End 输出**（后端 `run_workflow` 的 `outputs`）：

```json
{
  "is_compliant": "true 或 false（字符串，后端自行转布尔）",
  "compliance_reason": "合规：判定依据 / 不合规：风险条数摘要",
  "risks": [ { "clause": "...", "risk_level": "...", "violations": [...], "reference_case": {...} 或 null, "suggestion": "..." } ]
}
```

### 部署步骤

1. Dify 控制台 → 创建应用 → **导入 DSL 文件** → 选择 `dsl/合同审查.yml`。
2. 打开「知识检索」节点，绑定 3 个知识库：**法律法规库、某钢规章制度库、典型案例库**（DSL 中 `dataset_ids` 留空，导入后必须手动选择）。
3. 确认 DeepSeek 供应商已配置 API Key（两个 LLM 节点均为 `deepseek-chat`）；如插件支持，可在 LLM 节点手动开启 JSON mode 进一步约束输出。
4. 「知识检索」如已部署 rerank 模型，可开启重排序提升法条命中率。
5. 发布应用 → 「API 访问」生成 API Secret → 填入后端 `backend/.env` 的 `DIFY_CONTRACT_REVIEW_APP_KEY`（后端变量拆分完成后生效）。

### 验证用例

- **合规文本**：输入一段普通商务条款（如仅约定标的与价款）→ 期望 `is_compliant="true"`、`risks=[]`。
- **违规文本**：输入含「造成对方人身伤害的免责条款」等文本 → 期望 `is_compliant="false"`，`risks` 中 `violations` 指向《民法典》第五百零六条等真实依据，`suggestion` 结合典型案例。
- **解析兜底**：临时把 LLM-2 prompt 改成输出非 JSON → 期望 `parse_error=true`、`risks=[]`，流程不报错。

---

## 制度审查 Workflow

### 编排

与合同审查完全同构（两段式判定 + 分支 + 聚合器 + 单 End），差异点：

- 知识检索只挂 **2 库**：法律法规库、某钢规章制度库（无案例/审核规则/专家标注），Top K 5。
- LLM-1 判定语义为**冲突检测**：是否与上位法/现行制度冲突、越权或矛盾；文字表述/格式问题不算不合规。
- LLM-2 输出**无 `reference_case` 字段**，`violations`（law_name/article/description）与合同审查同名同构，`suggestion` 依据被冲突的上位条款给出。
- Code 节点兜底逻辑相同（解析失败按不合规处理）。

### 变量表

与合同审查一致（见上），仅 LLM-2 的 prompt 与检索库范围不同。

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
