# DEVELOPMENT.md
## 开发目标
本项目当前处于黑客松 Demo 初期阶段。

当前阶段目标不是实现完整产品，而是逐步验证以下核心闭环：

```text
用户目标
  ↓
Agent 理解和计算
  ↓
生成策略
  ↓
生成 Pact Proposal
  ↓
用户审批
  ↓
CAW 执行
  ↓
Audit Log 记录
  ↓
用户画像更新
```

---

## 开发阶段
### 阶段 0：项目初始化
目标：
- 建立目录结构；
- 建立开发规范；
- 建立日志制度；
- 明确前后端边界。

完成标准：
- `AGENTS.md` 存在；
- `DEVELOPMENT.md` 存在；
- `DEVELOPMENT_LOG.md` 存在；
- `docs` 基础文档存在；
- `README.md` 仍为空。

### 阶段 1：CAW 最小闭环
目标：
- 跑通 CAW 最小 transfer；
- 跑通一次合法操作；
- 跑通一次越权被拒绝操作；
- 能看到 audit log。

完成标准：
- 可以通过脚本执行一次测试网操作；
- 可以故意触发一次 Pact / Policy 拒绝；
- 有清楚的日志和截图说明。

### 阶段 2：CAW Contract Call
目标：
- 从普通转账升级到合约调用；
- 验证白名单合约限制；
- 验证非白名单合约被拒绝。

完成标准：
- 可以调用一个测试合约；
- 非授权合约调用被拒绝；
- 输出交易记录和拒绝原因。

### 阶段 3：Rule-based 稳定币管理 Agent
目标：
- 先不用 LLM；
- 用规则实现稳定币资金管理；
- 例如保留 10% 流动性，剩余资金准备部署。

完成标准：
- 可以读取模拟余额；
- 可以计算 reserve 和 deployable；
- 可以生成策略说明；
- 可以生成 Pact Proposal 草案。

### 阶段 4：用户资金画像 Memory
目标：
- 建立用户偏好文件；
- 用用户偏好影响策略；
- 记录用户接受 / 拒绝行为。

完成标准：
- 支持 `profile.json`；
- 支持 `memory.md`；
- 支持 `events.jsonl`；
- 策略会根据用户画像变化。

### 阶段 5：Aave Demo
目标：
- 接入 Aave 测试网 supply / withdraw；
- Agent 只能在 Pact 授权范围内执行。

完成标准：
- 能完成一次稳定币 supply；
- 能完成一次 withdraw；
- 超出 Pact 限制会失败；
- 前端或日志中能解释操作原因。

### 阶段 6：前端 Demo
目标：
- 建立最小聊天界面；
- 展示策略建议；
- 展示 Pact Proposal；
- 展示执行结果。

完成标准：
- 用户可以输入目标；
- 页面显示 Agent 推荐；
- 页面显示 Pact Proposal；
- 页面显示交易结果和审计日志。

---

## 分支规则
禁止直接在 `main` 上进行功能开发、修复或文档改动。

每个独立功能点、修复点或文档任务，应在一个非 main 分支上完成。同一功能点可以在同一分支内持续修改和优化，不需要每次提交都新建分支。

开始一个新功能点时：

```sh
git checkout main
git pull
git checkout -b <type>/<task-name>
```

示例：

```sh
git checkout -b chore/init-project-guidelines
git checkout -b feat/caw-transfer-demo
git checkout -b docs/caw-learning-notes
```

如果当前已经在该功能点对应的分支上，可以继续在该分支内开发，不需要重新创建分支。

任务完成后：

```sh
git status
```

然后总结修改内容，不要自动 merge。

---

## 日志规则
每个功能点、修复点或文档任务完成后，必须追加 `DEVELOPMENT_LOG.md`。

格式：

```md
## YYYY-MM-DD - 任务名称
- 修改：文件或模块
- 意图：本次任务目的
- 备注：可选
```

示例：

```md
## 2026-06-03 - 初始化开发规范
- 修改：AGENTS.md, DEVELOPMENT.md, docs
- 意图：建立 AI 协作开发规则和项目结构
- 备注：README.md 保持为空
```

---

## 前后端安排
### 前端
短期：
- 可以先为空；
- 只保留目录；
- 不实现 UI。

中期：
- 聊天输入；
- 策略展示；
- Pact Proposal 展示；
- 交易结果展示；
- Audit Log 展示。

### 后端
短期：
- CAW 脚本；
- 策略计算脚本；
- 本地 memory 文件读写。

中期：
- API 路由；
- Agent 编排；
- CAW SDK 封装；
- Pact Proposal 生成；
- 用户画像更新。

---

## 当前技术倾向
优先考虑：
- TypeScript；
- Node.js 后端；
- 简单文件存储；
- 后续再接 Next.js 或其他前端框架。

当前不做：
- 数据库；
- 复杂登录；
- 主网交易；
- 多协议聚合；
- 复杂策略回测。

---

## 核心设计边界
Strategy 负责“应该做什么”。

Pact 负责“允许做什么”。

CAW 负责“实际执行什么”。

Memory 负责“用户偏好是什么”。

Audit Log 负责“发生了什么”。

任何资金操作都必须通过 CAW。
