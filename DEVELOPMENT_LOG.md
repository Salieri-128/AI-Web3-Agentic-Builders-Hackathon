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

## 2026-06-07 - 实现 Sepolia 策略钱包

- 修改：apps/backend/app/services/treasury_service.py, apps/backend/app/main.py, apps/backend/app/schemas.py, apps/backend/app/services/agent_service.py, apps/frontend/src, DEVELOPMENT_LOG.md
- 意图：实现 CAW Sepolia 钱包状态、每日再平衡建议、内部调仓 Pact、外部转账 Pact 和转账统计
- 备注：外部转账可在 CAW Pact active 后真实执行，后端不再额外设置执行保护开关

## 2026-06-07 - 接入 Aave Sepolia USDC

- 修改：apps/backend/app/services/aave_service.py, apps/backend/app/services/caw_service.py, apps/backend/app/services/treasury_service.py, apps/backend/app/main.py, apps/frontend/src, DEVELOPMENT_LOG.md
- 意图：打通 Aave Sepolia USDC faucet、approve、supply、withdraw 的 CAW contract_call 链路
- 备注：已提交 Aave contract-call Pact，等待 CAW owner 审批

## 2026-06-07 - 重构前端标签页

- 修改：apps/frontend/src, apps/backend/app/main.py, DEVELOPMENT_LOG.md
- 意图：改为 Chat、Portfolio、Strategy、History 四个标签页，并展示链上资产组合
- 备注：Portfolio 使用现有 CAW/Aave 状态组装

## 2026-06-08 - 简化 Strategy 策略页

- 修改：apps/frontend/src/components/TreasuryPanel.tsx, apps/frontend/src/App.tsx, apps/frontend/src/styles.css
- 意图：让 Aave USDC 策略页面向普通用户展示策略说明、一键执行和资金流动性状态
- 备注：保留 CAW Pact 审批边界，前端只提交/刷新授权状态

## 2026-06-08 - 串联 Strategy Pact 审批流

- 修改：apps/backend/app/main.py, apps/backend/app/services/treasury_service.py, apps/frontend/src
- 意图：执行策略时先提交 CAW Rebalance Pact，等待用户审批后再执行 Aave 调仓
- 备注：前端审批弹窗会轮询 Pact 状态，策略成功后再展示资金结果

## 2026-06-08 - 修正 Strategy 假完成状态

- 修改：apps/backend/app/services/treasury_service.py, apps/frontend/src
- 意图：避免旧本地 Pact 被误判为真实 CAW 授权，并阻止 Aave 执行失败时显示完成
- 备注：只有带 caw_pact_id 的 active Pact 才可执行

## 2026-06-08 - 移除 Aave Faucet 路径

- 修改：apps/backend/app/services/aave_service.py, apps/backend/app/main.py, apps/backend/app/services/agent_service.py, apps/frontend/src/api.ts, data/users/demo
- 意图：Aave 策略 Pact 只允许 approve、supply、withdraw，不再包含 faucet 或本地领水流程
- 备注：清理旧本地 internal pact 和旧 faucet pact 记录

## 2026-06-08 - 验证 Aave Supply 执行

- 修改：apps/backend/app/services/caw_service.py, apps/backend/app/services/aave_service.py, DEVELOPMENT_LOG.md
- 意图：补齐 CAW contract_call 的 src_addr，并验证 100 USDC Aave supply 链路
- 备注：approve 成功，supply 因 Aave error 51 供应上限失败

## 2026-06-08 - 切换策略资产到 WBTC

- 修改：apps/backend/app/services/aave_service.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py, apps/frontend/src, data/users/demo
- 意图：将 Aave 生息策略主体从 USDC 改为 WBTC，并展示 WBTC/aWBTC 资产
- 备注：当前钱包检测到 1 WBTC，推荐保留 0.1 WBTC、投入 0.9 WBTC

## 2026-06-08 - 串联 Approve 后自动 Supply

- 修改：apps/backend/app/services/aave_service.py, DEVELOPMENT_LOG.md
- 意图：approve 提交后等待 allowance 生效，再自动执行 Aave supply
- 备注：已完成 0.9 WBTC supply，当前钱包 0.1 WBTC、Aave 0.9 aWBTC

## 2026-06-09 - 完善生息策略前端状态

- 修改：apps/frontend/src/App.tsx, apps/frontend/src/components/TreasuryPanel.tsx, apps/frontend/src/styles.css
- 意图：刷新后根据 Aave 仓位保持策略运行态，并支持取消策略取回资产
- 备注：取消策略复用已授权 Aave withdraw Pact

## 2026-06-09 - 新增策略数据页

- 修改：apps/frontend/src/App.tsx, apps/frontend/src/components/StrategyDataPanel.tsx, apps/frontend/src/styles.css
- 意图：展示保留流动性公式、用户画像、转账统计和策略参数
- 备注：复用现有 treasury/profile 数据

## 2026-06-09 - 串联 Chat 转账 Pact 流程

- 修改：apps/backend/app/services/agent_service.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/caw_service.py, apps/frontend/src/components/ChatPanel.tsx
- 意图：用户发起转账后自动检查 Pact、必要时提交并等待审批后执行
- 备注：修正地址中的 0x 被误识别为转账金额

## 2026-06-09 - 约束 LLM 资金流程边界

- 修改：apps/backend/app/services/llm_service.py, apps/backend/app/services/agent_service.py
- 意图：让 LLM 只做意图判断，资金转账统一由工具层固定流程执行
- 备注：转账结果回复不再交给 LLM 重新解释

## 2026-06-09 - 修正转账 Pact 限制

- 修改：apps/backend/app/services/caw_service.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py
- 意图：转账 Pact 使用 token 数量上限和 7 天时效，并明确审批后自动执行状态
- 备注：旧美元上限 transfer Pact 不再复用

## 2026-06-09 - 修正旧 Pact 识别

- 修改：apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py
- 意图：跳过已 active 但使用美元上限的旧 transfer Pact，并展示具体执行错误
- 备注：旧 Pact 可保留但不会再被本地匹配使用

## 2026-06-09 - 改为 LLM 引导转账流程

- 修改：apps/backend/app/services/llm_service.py, apps/backend/app/services/agent_service.py
- 意图：让 LLM 根据余额和 Pact 工具结果判断下一步，工具层继续执行硬约束
- 备注：成功回复会展示 CAW 返回的 gas fee

## 2026-06-09 - 修正 CAW 转账源地址

- 修改：apps/backend/app/services/caw_service.py
- 意图：调用 CAW transfer_tokens 时传入钱包 src_addr
- 备注：避免 CAW API 返回 src_addr missing 的 422

## 2026-06-09 - 修正本地 Pact ID 映射

- 修改：apps/backend/app/services/treasury_service.py
- 意图：执行转账前将本地 pact_id 解析为 CAW pact UUID
- 备注：避免 CAW API 将 pact-transfer-local-* 当作 UUID 导致 422

## 2026-06-09 - Review 外部转账字段链路

- 修改：apps/backend/app/services/caw_service.py, apps/backend/app/services/agent_service.py
- 意图：确保 CAW transfer_tokens 所需 wallet_id、src_addr、dst_addr、token_id、amount 等字段完整传递
- 备注：移除 contract_call 路径误加的源地址查询

## 2026-06-09 - 修正 CAW 转账 Token ID

- 修改：apps/backend/app/services/agent_service.py, apps/backend/app/services/llm_service.py, apps/backend/app/services/treasury_service.py
- 意图：外部转账使用 CAW 可识别的 WBTC token_id，链用 SETH 单独传递
- 备注：含 SETH_WBTC 的旧 transfer Pact 不再复用

## 2026-06-09 - 修正撤销 Pact 后复用

- 修改：apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py
- 意图：每次转账前刷新 external Pact 状态，只允许 active 且匹配的 Pact 执行
- 备注：revoked/pending/legacy Pact 不再被 LLM fallback 或后端匹配复用

## 2026-06-09 - 改用 ERC20 Contract Call 转账

- 修改：apps/backend/app/services/aave_service.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py
- 意图：Sepolia Aave WBTC 不走 CAW 内置 token transfer，改为 WBTC.transfer contract_call
- 备注：Pact 限制 WBTC 合约、目标地址、raw amount、次数和 7 天时效

## 2026-06-09 - 移除 LLM 转账 USD 限额

- 修改：apps/backend/app/services/agent_service.py, apps/backend/app/services/llm_service.py
- 意图：外部转账请求只向 LLM 暴露 token 数量约束，避免按 USD 限额误判
- 备注：amount/max_amount 均为同币种数量

## 2026-06-09 - 补齐 Pact 生效后继续转账

- 修改：apps/backend/app/main.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py, apps/frontend/src/App.tsx, apps/frontend/src/api.ts
- 意图：Pact approve 后由前端轮询后端 pending transfer 执行入口继续 WBTC 转账
- 备注：本地 Pact 记录保存 pending_execution 的目标地址和金额

## 2026-06-09 - 优化转账监听和 Gas 展示

- 修改：apps/backend/app/main.py, apps/backend/app/services/treasury_service.py, apps/backend/app/services/agent_service.py, apps/frontend/src/App.tsx, apps/frontend/src/api.ts
- 意图：Pact 生效后先提示正在交易，并在 CAW 未返回 gas fee 时展示交易状态
- 备注：新增 pending transfer status 查询入口

## 2026-06-09 - 查询 CAW 交易详情费用

- 修改：apps/backend/app/services/caw_service.py, apps/backend/app/services/aave_service.py, apps/backend/app/services/agent_service.py, apps/frontend/src/App.tsx
- 意图：转账提交后按 request_id 查询 Cobo 交易详情并展示 fee
- 备注：兼容交易详情尚未返回 fee 的处理中状态

## 2026-06-09 - 区分转账等待和执行状态

- 修改：apps/frontend/src/App.tsx, apps/frontend/src/components/ChatPanel.tsx, apps/backend/app/services/aave_service.py, apps/backend/app/services/agent_service.py
- 意图：已有 Pact 时前端显示交易中，并从 CAW 详情多路径提取 gas fee
- 备注：优先展示实际链上 gas，缺失时展示 estimated fee

## 2026-06-09 - 修正新 Pact 转账返回链路

- 修改：apps/backend/app/services/agent_service.py, apps/backend/app/services/aave_service.py, apps/frontend/src/App.tsx
- 意图：新 Pact 提交后立即返回给前端监听，避免长请求断连覆盖成功结果
- 备注：状态刷新失败不再覆盖聊天主回复
