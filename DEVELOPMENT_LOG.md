# DEVELOPMENT_LOG.md

本文件用于记录 AI / Codex / 开发者每个功能点、修复点或文档任务完成后的极简开发日志。

要求：

- 每个功能点、修复点或文档任务完成后追加。
- 只写极简总结。
- 不写长篇解释。
- 不记录无意义细节。

格式：

```md
## YYYY-MM-DD - 任务名称
- 修改：文件或模块
- 意图：为什么做
- 备注：可选
```

---

## 2026-06-03 - 初始化开发规范

- 修改：AGENTS.md, DEVELOPMENT.md, DEVELOPMENT_LOG.md, docs, 初始目录
- 意图：建立 AI 协作开发规则、项目结构和日志制度
- 备注：README.md 保持为空，未实现业务逻辑

## 2026-06-03 - 添加 Git 忽略规则

- 修改：.gitignore, DEVELOPMENT_LOG.md
- 意图：避免依赖、密钥、本地文件和 Demo 用户数据误传到远端仓库
- 备注：保留 data/users/.gitkeep 用于提交目录结构

## 2026-06-04 - 初始化 Stage 1 Agentic Treasury Demo

- 修改：apps/backend, apps/frontend, data/users/profile.json, DEVELOPMENT_LOG.md
- 意图：打通 Frontend、Backend Agent、Local Memory 和 CAW read-only 查询闭环
- 备注：资金操作仅生成 proposal，不执行真实交易

## 2026-06-04 - 接入 LLM 与 CAW 工具层

- 修改：apps/backend, apps/frontend, DEVELOPMENT_LOG.md
- 意图：让前端通过后端调用 LLM，并接入 CAW 钱包查询、Pact proposal 和受保护交易入口
- 备注：真实交易需 CAW_ENABLE_REAL_EXECUTION=true 且 Pact active

## 2026-06-04 - 适配 Paratera LLM 配置

- 修改：apps/backend/app/config.py, apps/backend/app/services/llm_service.py, apps/backend/.env.example, DEVELOPMENT_LOG.md
- 意图：支持 API_URL/BASE_URL/MODEL 等传统变量名，并为不可用模型增加 fallback
- 备注：deepseek-v4-pro 当前无健康部署时会自动尝试备用模型

## 2026-06-04 - 修正 Paratera 模型名

- 修改：apps/backend/.env.example, DEVELOPMENT_LOG.md
- 意图：使用平台支持列表中的精确模型名 DeepSeek-V4-Pro
- 备注：模型名大小写敏感

## 2026-06-04 - 调整前端分页与 Chat 回复

- 修改：apps/frontend/src/App.tsx, apps/frontend/src/components/ChatPanel.tsx, apps/frontend/src/styles.css, apps/backend/app/services/agent_service.py, DEVELOPMENT_LOG.md
- 意图：将 Chat 与 Profile 分页，并让钱包查询回复包含余额摘要
- 备注：Chat 页仅显示当前一次问答

## 2026-06-04 - 改为 AI 最终回复

- 修改：apps/backend/app/services/llm_service.py, apps/backend/app/services/agent_service.py, apps/backend/app/services/caw_service.py, apps/frontend/src/components/ChatPanel.tsx, apps/frontend/src/styles.css, DEVELOPMENT_LOG.md
- 意图：让 Chat 在工具查询后由 LLM 生成最终回答，并修正 CAW 余额字段
- 备注：SETH 余额读取 amount/total 字段

## 2026-06-07 - 调整分支合并规则

- 修改：AGENTS.md, DEVELOPMENT_LOG.md
- 意图：允许用户明确要求时由 AI / Codex 执行 merge
- 备注：默认仍不自动合并
