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
