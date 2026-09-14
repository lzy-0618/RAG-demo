# frontend（Vue 3 + Vite + TypeScript + Element Plus + Pinia）

企业合规智能平台前端。开发期通过 Vite 代理把 `/api` 转发到后端 `http://127.0.0.1:8000`，见 `vite.config.ts`。

## 本地运行

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # vue-tsc 类型检查 + 构建
```

后端需同时运行（`cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000`）。

## 目录约定

```
src/
├── api/         # axios 封装与接口定义（http/auth/chat/knowledge/generate）
├── views/       # 页面：登录、问答、知识库、审查、生成、模板、纠错
├── stores/      # Pinia（user：token 与登录态）
├── router/      # 路由与登录守卫（未登录跳 /login）
└── main.ts
```

## 已联调页面

| 页面 | 状态 | 说明 |
| --- | --- | --- |
| 登录 `/login` | ✅ | 真实口令校验（后端 PBKDF2 哈希）；开发环境页面提示种子账号，登录后顶栏显示角色 |
| 智能问答 `/chat` | ✅ | SSE 流式、多轮（conversation_id）、引用来源卡片；**不设咨询类别**；**专家可就地标注纠错**（需求⑤，非专家不可见） |
| 知识库管理 `/knowledge` | ✅ | 选库、上传入库、文本入库、状态轮询、刷新状态、删除、从 Dify 同步 |
| 合同审查 `/review` | ✅ | 文本/文件提交、进度条轮询、风险卡片（条款/等级/依据/案例/建议） |
| 制度审查 `/review/regulation` | ✅ | 同上，共用 `components/ReviewPanel.vue`，仅审查类型不同 |
| 合同模板库 `/templates` | ✅ | 导入 .docx 模板（自动解析 `{{ 变量 }}`）、分类筛选、下载、删除 |
| 合同生成 `/generate/contract` | ✅ | 选模板 → 按占位变量动态表单填写 → docxtpl 填充 → 下载 Word |
| 规章制度生成 `/generate/regulation` | ✅ | 需求 → 大纲（可编辑）→ 全文 → 自动合规审查（修正轮次/审查进度轮询）→ 下载 |
| ~~内容纠错~~ `/correct` | 已删除 | 改为聊天页专家就地标注（需求⑤） |

## 联调注意点

1. **SSE 事件分隔符是 CRLF**：sse-starlette 用 `\r\n\r\n` 分隔事件，前端按 `\n\n` 切分会一条事件都解析不到（页面表现为「问题发出去了、回答空白」）。`api/chat.ts` 用 `/\r?\n\r?\n/` 兼容两种换行，且支持多行 `data:`。
2. **接口响应结构不统一**：知识库接口是 `{ code, message, data }`，对话/登录是裸对象（`ChatResponse` / `TokenResponse`）。`api/http.ts` 的响应拦截器返回 `response.data`，各接口按自己的类型声明泛型。
3. **错误与 401 统一处理**在 `api/http.ts`：业务错误弹 `message`，401 清 token 并跳登录页。
4. **上传超时**：审查/生成链路含多轮 LLM 调用，axios 超时设为 300s；对话用 `fetch` 流式读取，不受 axios 超时限制。
5. **浏览器自动化不能测文件选择**：IAB 不支持 file chooser，文件上传路径需用接口或人工验证（已通过接口端到端验证）。
