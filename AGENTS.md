# AGENTS.md
## 项目定位
本项目是一个黑客松 Demo，目标是构建一个基于 Cobo Agentic Wallet 的 AI 稳定币资金管理 Agent。

核心原则：
> Agent 负责决策，Pact 负责约束，CAW 负责执行，Audit Log 负责解释。

本项目不是无限权限的 AI 交易 Bot，也不是高风险自动炒币系统。项目重点是展示：
- AI 如何根据用户目标和资金画像生成资金管理策略；
- AI 如何提出 CAW Pact Proposal；
- 用户如何审批 Pact；
- Agent 如何在用户授权边界内执行；
- CAW 如何作为资金安全和权限控制层。

---

## 分支开发流程
所有 AI Coding Agent / Codex / 开发者必须遵守：
1. 禁止直接在 `main` 分支上进行功能开发、修复或文档改动。
2. 每个独立功能点、修复点或文档任务，应在一个对应的非 main 分支上完成。
3. 同一个功能点可以在同一个分支内多次迭代，不需要每次小修改都新开分支。
4. 当一个功能点完成并确认无误后，再由用户决定是否合并回 `main`。
5. 默认不允许 AI / Codex 自动 merge 到 `main`；但当用户在当前对话中明确要求合并时，AI / Codex 可以执行 merge。
6. 分支命名建议：`chore/...`、`feat/...`、`fix/...`、`docs/...`、`refactor/...`。
7. 一个分支应尽量只对应一个清晰目标，避免把多个无关功能混在一起。
8. 完成任务后必须说明当前分支名、修改文件、做了什么、为什么这么做、是否还有未完成事项。

---

## 开发日志要求
每次完成一个功能点、修复点或文档任务后，都必须在 `DEVELOPMENT_LOG.md` 追加极简日志。

日志格式：
```md
## YYYY-MM-DD - 任务名称
- 修改：涉及的文件或模块
- 意图：为什么做这件事
- 备注：可选，极简说明
```

要求：
- 日志必须简短。
- 不要写长篇总结。
- 不要记录无意义细节。
- 每个功能点 / 修复点 / 文档任务完成后都要追加。

---

## 项目结构约定
当前采用适合黑客松的前后端分离结构：

```text
apps/
  frontend/        # 未来前端：聊天 UI、策略展示、Pact Proposal 展示、交易结果展示
  backend/         # 未来后端：API、Agent 编排、CAW 调用、策略执行
packages/
  agent/           # Agent 编排逻辑
  caw/             # Cobo Agentic Wallet 集成
  memory/          # 用户资金画像与记忆层
  strategy/        # 稳定币资金配置策略
docs/
  ARCHITECTURE.md  # 架构说明
  ROADMAP.md       # 路线图
  CAW_NOTES.md     # CAW 学习笔记
data/
  users/           # Demo 阶段本地用户画像和事件日志
```

---

## 前端职责
前端未来负责：
- 对话界面；
- 用户输入 LLM API Key；
- 钱包 / CAW 连接流程；
- 展示用户资金画像；
- 展示 Agent 推荐策略；
- 展示 Pact Proposal；
- 展示用户审批状态；
- 展示交易结果和 Audit Logs。

前端不应该：
- 保存私钥；
- 绕过后端直接执行资金策略；
- 直接承担资金风控逻辑；
- 在未明确设计前保存敏感信息。

早期 Demo 阶段可以先不做前端。

---

## 后端职责
后端未来负责：
- 调用用户选择的 LLM 服务；
- 管理用户资金画像；
- 运行策略计算；
- 生成 CAW Pact Proposal；
- 调用 CAW SDK / API；
- 返回交易状态和审计信息。

后端必须把以下模块分开：

```text
用户输入
  ↓
用户画像 / memory
  ↓
策略计算 strategy
  ↓
Pact Proposal 生成
  ↓
CAW 执行
  ↓
Audit Log 记录
```

---

## CAW 安全原则
CAW 是执行层和风控层。

Pact 不是策略引擎。Pact 是权限边界。

Agent 可以：
- 计算策略；
- 生成建议；
- 生成 Pact Proposal；
- 请求用户审批；
- 在已批准的 Pact 范围内执行操作。

Agent 不可以：
- 自己批准 Pact；
- 自己提高额度；
- 自己扩展白名单；
- 调用未授权合约；
- 向任意地址转账；
- 绕过 CAW 执行资金操作；
- 把用户画像当成资金授权。

如果当前 Pact 不足，Agent 应该提出新的 Pact Proposal，并等待用户审批。

---

## 用户画像 / Memory 原则
用户画像用于影响策略，不用于授权资金。

可以记录：
- 风险偏好；
- 常用稳定币；
- 偏好的协议；
- 拒绝的策略；
- 流动性保留比例；
- 单次交易偏好额度；
- 用户历史接受 / 拒绝行为；
- 对未来策略有帮助的自然语言记忆。

禁止记录：
- 私钥；
- 明文 API Key；
- 不必要的敏感个人信息；
- 任何可以直接控制资金的凭证。

Demo 阶段建议结构：

```text
data/users/<userId>/profile.json
data/users/<userId>/memory.md
data/users/<userId>/events.jsonl
```

---

## Demo 优先原则
这是黑客松项目，优先做可演示闭环，不要过早工程化。

推荐开发顺序：
1. 项目规范和目录初始化；
2. CAW 最小转账 Demo；
3. CAW Pact 拒绝 Demo；
4. Rule-based 稳定币管理 Agent；
5. 用户资金画像 Memory；
6. Aave supply / withdraw Demo；
7. 对话 UI 和 Demo 打磨。

避免过早实现：
- 复杂数据库；
- 完整登录系统；
- 高级前端动画；
- 多协议收益聚合；
- Uniswap V3 LP；
- 杠杆 / 借贷策略；
- 主网真实资金执行。

---

## 代码风格
- 优先使用 TypeScript。
- 保持模块小而清晰。
- 命名要直观。
- 不要过度抽象。
- 不要添加重依赖。
- 不要提交 `.env`。
- 不要提交私钥或 API Key。
- 对非显而易见的资金逻辑添加简短注释。
- 所有资金相关动作必须可解释、可审计。

---

## 未经明确要求，不要做的事
未经用户明确要求，不要：
- 修改 `README.md`；
- 添加真实主网执行；
- 接入复杂 DeFi 策略；
- 添加 leverage / borrow；
- 添加 Uniswap LP；
- 添加数据库；
- 添加登录系统；
- 添加大型前端框架；
- 存储私钥；
- 存储明文 API Key；
- 自动 merge 到 `main`。
