# StableFlow Agent Proposal

## 一句话简介

StableFlow Agent 是一个由 AI 规划资金、CAW Pact 约束权限、Cobo Agentic Wallet 执行交易并由 Audit Log 解释结果的链上账户管理 Agent。

## 问题

链上用户往往需要在两类需求之间反复权衡：

1. 保留足够余额，以便随时收款、转账和支付 Gas。
2. 减少长期闲置资金，把暂时不用的资产配置到低风险生息协议。

普通用户很难持续跟踪余额、未来支出、Gas 成本、协议仓位和授权状态。传统自动交易程序又常拥有过宽权限，一旦策略错误或凭证泄露，风险会直接传导到资金。

本项目的灵感来自货币银行学课程中的创新题：如果 Agent 能辅助完成交易和流动性管理，使资金更高效地在支付用途与收益用途之间切换，就可能降低用户维持大量闲置货币余额的需求，提高资金使用效率，并在更大范围内改善社会福利。

## 解决方案

StableFlow Agent 将策略与权限拆分：

- Agent 理解用户目标，结合余额、历史转账和资金画像生成建议。
- 确定性 Policy 计算流动性目标、Aave 仓位、Gas 成本和操作金额。
- Agent 为必要操作提出最小权限 CAW Pact Proposal。
- 用户在 Cobo/CAW App 中审批、拒绝或撤销 Pact。
- CAW 只在 Pact 允许的链、资产、合约、方法、额度和有效期内执行。
- Audit Log 记录建议、审批、执行、拒绝和失败原因。

```text
用户目标 / Memory
        ↓
LLM Planner + Treasury Policy
        ↓
策略建议 / Pact Proposal
        ↓
Owner Approval
        ↓
CAW Execution
        ↓
Sepolia / Aave V3 / Audit Log
```

## 目标用户

目标用户是不希望每天手动管理链上头寸，但仍希望保留资金控制权的人。

在默认模式下，用户主要关注：

- 查看余额和收款地址；
- 发起日常转账；
- 在需要时审批 Agent 提出的权限；
- 查看交易结果和审计记录。

当用户希望进一步优化时，可以告诉 Agent 未来支出、最低保留金额、风险偏好或低 Gas 偏好。Agent 会提出 Memory 或策略变更，用户确认后才会生效。用户画像不会自动转化成资金授权。

## 技术实现

### Frontend

React、TypeScript 和 Vite 构建钱包与资金优化控制台，展示：

- 对话和普通钱包操作；
- WBTC 钱包余额与 Aave 仓位；
- Agent 策略建议；
- Pact Proposal 和审批状态；
- 用户画像变更提案；
- 交易结果、Gas fee 和 Audit Log。

### Backend

FastAPI 负责编排以下模块：

- Agent Orchestrator：识别钱包操作、策略操作和用户画像请求。
- LLM Planner：通过 OpenAI-compatible API 理解复合资金目标并生成解释。
- Treasury Policy：使用确定性规则计算流动性、调仓和经济性边界。
- Memory：使用本地 JSON/Markdown/JSONL 保存非敏感用户偏好和事件。
- CAW Service：调用 Cobo Agentic Wallet SDK/API 查询钱包、提交 Pact 和执行操作。
- Aave Service：构造 Sepolia WBTC `approve`、Aave V3 `supply` / `withdraw` 调用。

### 权限模型

Aave Rebalance Pact 只允许：

- 网络：Ethereum Sepolia；
- 资产：指定 WBTC；
- 合约：指定 WBTC 和 Aave V3 Pool；
- 方法：`approve`、`supply`、`withdraw`；
- 上限：指定 WBTC 额度；
- 结束条件：限定时间或交易次数。

外部转账使用独立 Pact，并绑定收款地址、资产、额度、次数和有效期。Agent 不能自行审批或扩大任何权限。

## 当前完成度

已完成：

- CAW 钱包状态、Pact 和审计数据接入；
- Sepolia WBTC 外部转账；
- Aave V3 WBTC approve / supply / withdraw；
- Pact 提交、人工审批、状态轮询和失败停止；
- 基于余额、历史行为、画像和 Gas 的资金策略；
- 用户画像 Memory Proposal；
- LLM Treasury Planner；
- React 钱包与资金优化 UI；
- 本地状态重置、50 个后端测试和前端生产构建；
- 可重复执行的 Sepolia Demo 流程。

待补充：

- 3–5 分钟演示视频链接；
- 提交页面中的完整交易哈希列表。

## 测试网证据

CAW Agent Wallet：

[`0x91e1a82ae48998f8ec577fa895764d957dce7a94`](https://sepolia.etherscan.io/address/0x91e1a82ae48998f8ec577fa895764d957dce7a94)

关键合约：

- [Sepolia WBTC](https://sepolia.etherscan.io/address/0x29f2d40b0605204364af54ec677bd022da425d03)
- [Sepolia aWBTC](https://sepolia.etherscan.io/address/0x1804bf30507dc2eb3bdebbbdd859991eaef6eeff)
- [Aave V3 Pool](https://sepolia.etherscan.io/address/0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951)

### Pact 概览

![CAW Pacts overview](assets/evidence/caw-pacts-overview.png)

### Pact 风险边界

![Aave Pact risk controls](assets/evidence/aave-pact-risk-controls-1.png)

![Aave Pact risk controls second capture](assets/evidence/aave-pact-risk-controls-2.png)

### 合约调用结果

![WBTC contract call success](assets/evidence/wbtc-contract-call-success.png)

![Aave contract call success](assets/evidence/aave-contract-call-success.png)

## 安全、失败处理与人工介入

- Demo 仅运行在 Ethereum Sepolia，不使用主网真实资金。
- 私钥不进入项目；API Key 仅放在本地 `.env`。
- LLM 负责理解和解释，不绕过后端 Policy 直接执行。
- Pact 未批准、已撤销、已过期或额度不足时，Agent 提交新 Proposal 并等待用户。
- 余额不足、Gas 不足、价格不可用或收益无法覆盖成本时，Policy 返回 `hold` 或失败状态。
- CAW 或链上调用失败时，不显示为成功，不自动扩权重试。
- 用户可以在 Cobo/CAW App 中拒绝或撤销 Pact，并人工处理异常仓位。

## Hackathon 期间新增贡献

项目仓库于 2026 年 6 月 1 日创建。本次 Hackathon 期间完成了从项目规范到可演示闭环的主要工作，包括 CAW、Aave、Pact、Agent、Memory、LLM Planner、前端、测试和提交材料。

## 后续计划

- 接入更多链上资产，优先加入更多稳定币。
- 增加更多低风险策略和协议。
- 支持用户定义策略目标和更细粒度 Pact 模板。
- 完善异常恢复、跨协议审计和策略评估。
- 在安全验证后探索更多测试网络与部署方式。

## 团队

- 成员：Jia Xu
- 角色：独立开发者，负责产品、Agent、前后端和链上集成
- 钱包：`0x91e1a82ae48998f8ec577fa895764d957dce7a94`
- 微信：`Salieri128`

## 第三方与 AI 工具披露

项目使用 Cobo Agentic Wallet SDK/API、Aave V3 Sepolia contracts、OpenAI-compatible LLM API、Paratera API 示例配置，以及 React、TypeScript、Vite、FastAPI 等开源项目。

开发过程中使用 OpenAI Codex 辅助编码、测试、文档和审查，并使用 Codex `frontend-design` Skill 辅助前端设计与实现。
