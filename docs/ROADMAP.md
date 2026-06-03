# Roadmap
## Milestone 0：项目初始化
目标：
- 建立开发规范；
- 建立目录结构；
- 建立日志制度；
- 保持 README.md 为空。

状态：
- 待完成。

---

## Milestone 1：CAW Transfer Demo
目标：
- 跑通 CAW 最小转账；
- 完成一次合法测试网操作；
- 完成一次越权被拒绝操作。

产出：
- 脚本；
- 操作记录；
- audit log。

---

## Milestone 2：CAW Pact Denial Demo
目标：
- 展示 CAW 如何拒绝越权操作；
- 明确 Pact 是风险边界。

场景：
- 超额转账；
- 非白名单 token；
- 非白名单地址；
- pact 过期。

---

## Milestone 3：Rule-based Stablecoin Manager
目标：
- 不依赖 LLM；
- 根据固定规则计算资金配置。

示例：
- 用户有 1000 USDC；
- 保留 100 USDC；
- 其余 900 USDC 作为 deployable；
- 生成 Pact Proposal。

---

## Milestone 4：User Treasury Profile
目标：
- 建立用户资金画像；
- 用画像影响策略。

文件：
- `profile.json`
- `memory.md`
- `events.jsonl`

示例：
- 用户偏好保守；
- 用户拒绝 LP；
- 用户偏好 Aave；
- 用户希望保留 10% 流动性。

---

## Milestone 5：Aave Supply / Withdraw Demo
目标：
- 接入 Aave 测试网；
- 完成 supply；
- 完成 withdraw；
- 通过 Pact 限制执行边界。

---

## Milestone 6：Chat UI
目标：
- 用户通过对话表达目标；
- Agent 返回策略；
- 前端展示 Pact Proposal；
- 展示执行结果。

---

## Milestone 7：Demo Polish
目标：
- 准备演示脚本；
- 准备 README 或提交说明；
- 准备 Demo 视频；
- 准备测试网地址、交易 hash、Agent Wallet 地址。

注意：
当前要求 `README.md` 保持为空。后续只有在明确要求时再填写 README。
