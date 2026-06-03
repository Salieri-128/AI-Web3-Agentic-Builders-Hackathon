# CAW Notes
本文件记录 Cobo Agentic Wallet 学习笔记。

## 当前理解
CAW 可以理解为：

```text
Agent 提出资金操作
  ↓
CAW 根据 Pact / Policy 检查
  ↓
允许则执行
  ↓
越权则拒绝或要求审批
  ↓
记录 Audit Log
```

---

## 核心概念
### Agent
Agent 是执行任务的程序，可以是规则程序，也可以接入 LLM。

Agent 负责：
- 理解用户目标；
- 计算策略；
- 生成执行计划；
- 提出 Pact Proposal；
- 在已批准 Pact 内执行。

Agent 不应该：
- 自己批准 Pact；
- 自己提高权限；
- 直接绕过 CAW 控制资金。

### Owner
Owner 是人类用户或资金控制者。

Owner 负责：
- 审批 Pact；
- 拒绝 Pact；
- 撤销权限；
- 管理资金边界。

### Pact
Pact 是 Agent 的授权合同。

Pact 定义：
- 允许的链；
- 允许的 token；
- 允许的合约；
- 允许的方法；
- 单次额度；
- 总额度；
- 有效期；
- 交易次数；
- 完成条件。

Pact 不是策略引擎，不负责复杂计算。

### Policy
Policy 是更具体的规则约束。

Policy 用于判断某次操作是否允许。

### Audit Log
Audit Log 用于记录 Agent 的资金操作和拒绝记录。

Demo 中 Audit Log 很重要，因为它能展示：
- Agent 做了什么；
- 为什么被允许；
- 为什么被拒绝；
- 资金操作是否可审计。

---

## 对本项目的意义
本项目中的稳定币资金管理逻辑应该是：

```text
Agent / Strategy Engine 计算策略
  ↓
Pact Proposal 表达授权请求
  ↓
用户审批
  ↓
CAW 检查和执行
```

不能把策略计算写进 Pact。

Pact 是最后的安全边界。
