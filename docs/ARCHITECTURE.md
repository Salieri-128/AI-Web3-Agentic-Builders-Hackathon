# Architecture
## 总体架构
本项目采用黑客松友好的分层结构：

```text
Frontend
  ↓
Backend API
  ↓
Agent Orchestrator
  ↓
Strategy Engine
  ↓
Pact Proposal Builder
  ↓
CAW Execution Layer
  ↓
Audit Log
```

---

## Frontend
前端负责和用户交互。

未来功能：
- 对话输入；
- 用户 API Key 输入；
- 钱包连接；
- 策略展示；
- Pact Proposal 展示；
- 执行结果展示；
- Audit Log 展示。

当前阶段：
- 前端先不实现；
- 只保留目录。

---

## Backend
后端负责业务编排。

未来功能：
- 接收用户目标；
- 调用 LLM；
- 读取用户画像；
- 生成策略；
- 生成 Pact Proposal；
- 调用 CAW；
- 返回执行结果。

---

## Agent Layer
Agent 负责理解目标、组织工具调用、生成解释。

Agent 不直接拥有无限资金权限。

Agent 不能绕过 CAW。

Agent 需要在 Pact 授权范围内行动。

---

## Strategy Layer
Strategy Layer 负责计算。

例子：

```text
用户余额：1000 USDC
用户希望保留：10%
reserve = 100 USDC
deployable = 900 USDC
```

Strategy Layer 可以根据：
- 用户风险偏好；
- 协议 APY；
- 白名单协议；
- 当前余额；
- 历史行为；

生成策略建议。

---

## Pact Proposal Layer
Pact Proposal Layer 负责把策略转换成 CAW 可审批的授权请求。

例如：

```text
允许资产：USDC
允许协议：Aave
允许方法：supply / withdraw
单次额度：300 USDC
总额度：900 USDC
有效期：24h
禁止：borrow, leverage, unknown transfer
```

---

## CAW Execution Layer
CAW 是资金执行和风控边界。

CAW 负责：
- 检查 Pact；
- 检查 Policy；
- 执行交易；
- 拒绝越权操作；
- 记录 Audit Log。

CAW 不负责：
- 替 Agent 计算策略；
- 替用户决定风险偏好；
- 自动扩大授权范围。

---

## Memory Layer
Memory Layer 负责用户资金画像。

它影响策略推荐，但不等于资金授权。

可以记录：
- 风险偏好；
- 保留流动性比例；
- 偏好协议；
- 拒绝策略；
- 历史操作。

不得记录：
- 私钥；
- 明文 API Key；
- 可以直接控制资金的凭证。
