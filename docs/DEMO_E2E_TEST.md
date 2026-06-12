# Demo 端到端测试路径

本流程基于 2026-06-12 清理后的真实 Sepolia 状态：

- 钱包：`1.00000001 WBTC`
- Aave：`0 WBTC`
- Gas：`0.02865646 SETH`
- 默认画像：`balanced`
- 默认建议保留：`0.1 WBTC`
- 本地 Pact、pending transfer、历史和 Planner 数据：空

链上余额变化后，请先查询余额，再按相同比例调整测试金额。

## 0. 清理状态

1. 停止后端进程。
2. 在 Cobo/CAW 中撤销或删除所有 Demo Pact。
3. 确认 Aave 仓位为 `0 WBTC`。如果不为 0，先通过已授权流程取回资产。
4. 执行：

```bash
python3 scripts/reset_demo_state.py --yes
```

该命令只清理本地数据，不撤销远端 Pact，也不移动链上资金。

## 1. 启动应用

后端：

```bash
PYTHONPATH=apps/backend uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```bash
cd apps/frontend
npm run dev -- --host 127.0.0.1
```

打开 `http://127.0.0.1:5173`。

## 2. 查询余额

在 Wallet 首页点击“查看余额”。

预期：

- 钱包约 `1.00000001 WBTC`
- Aave `0 WBTC`
- 建议保留 `0.1 WBTC`
- 本地没有 Pact 或 pending transfer
- Funds optimization 页面只显示策略执行区，不显示资金目标

## 3. 首次执行策略

1. 进入 Funds optimization。
2. 点击“执行策略”。
3. 在 Cobo/CAW 审批新建的 Aave Rebalance Pact。
4. 等待 supply 完成。

预期：

- Agent 建议向 Aave 存入约 `0.90000001 WBTC`
- 钱包约 `0.1 WBTC`
- Aave 约 `0.90000001 WBTC`
- 策略状态变为已执行
- 下方资金优化目标和高级数据解锁

## 4. 第一次转账：钱包余额可覆盖

使用你控制的 Sepolia EVM 地址作为收款地址，转账：

```text
0.02 WBTC
```

预期：

- 创建目标地址限定的 Transfer Pact，需要在 Cobo/CAW 审批
- 不触发 Aave withdraw
- 转账完成后钱包约 `0.08 WBTC`
- Aave 仍约 `0.90000001 WBTC`
- 总资金约 `0.98000001 WBTC`

## 5. 第二次转账：需要 Aave 补充流动性

向同一地址转账：

```text
0.15 WBTC
```

预期：

- `0.15 WBTC` 超过钱包当前约 `0.08 WBTC`
- 第一笔 Transfer Pact 的单笔额度不足，因此会提出新的 Transfer Pact
- 审批后复用已生效的 Aave Rebalance Pact
- Aave withdraw 约 `0.2755 WBTC`
- 随后完成 `0.15 WBTC` 转账
- 转账后钱包约 `0.2055 WBTC`
- Aave 约 `0.62450001 WBTC`
- 总资金约 `0.83000001 WBTC`

取款量不只覆盖余额缺口，还覆盖转账后的流动性目标：

```text
0.15 + 0.2055 - 0.08 = 0.2755 WBTC
```

## 6. 收款并 Rebalance

从外部测试钱包向 Treasury 地址发送：

```text
0.30 WBTC
```

Treasury 地址：

```text
0x91e1a82ae48998f8ec577fa895764d957dce7a94
```

点击“Sync now”，或等待后台同步。

预期同步后：

- 显示收到约 `0.30 WBTC`
- 钱包约 `0.5055 WBTC`
- Aave 约 `0.62450001 WBTC`
- 总资金约 `1.13000001 WBTC`
- 建议保留仍约 `0.2055 WBTC`
- Rebalance 建议向 Aave 存入约 `0.30 WBTC`

再次点击执行策略。

预期执行后：

- 钱包约 `0.2055 WBTC`
- Aave 约 `0.92450001 WBTC`
- 总资金约 `1.13000001 WBTC`

Gas 价格或资产价格不可用时，系统可能因经济性保护返回 `hold`。此时应先检查价格与 Gas 估算，而不是强行执行。

## 7. 用户画像：最低保留

在 Funds optimization 输入：

```text
至少保留 0.5 WBTC
```

预期：

- 返回 Memory Proposal，不立即修改画像
- 展示保留目标从约 `0.2055` 增至 `0.5 WBTC`
- 展示 Aave 目标从约 `0.92450001` 降至 `0.63000001 WBTC`
- Pact、白名单和执行权限不发生变化

确认提案后：

- profile 的 `liquidity_floor` 变为 `0.5`
- 建议保留变为 `0.5 WBTC`
- Rebalance 建议从 Aave 取回约 `0.2945 WBTC`

点击“重新调整”后，预期：

- 钱包约 `0.5 WBTC`
- Aave 约 `0.63000001 WBTC`

## 8. 用户画像：低 Gas 偏好

输入：

```text
以后不要频繁调仓，开启低 Gas 偏好
```

预期：

- 返回待确认的 Memory Proposal
- `prefers_low_gas` 从 `false` 变为 `true`
- `min_rebalance_amount` 从 `0.001` 提高到 `0.01`
- `gas_safety_multiplier` 从 `1.20` 提高到 `1.5`
- 不修改任何 Pact 或执行权限

## 9. 最终检查

- Audit trail 包含 supply、两次 transfer、自动 withdraw、收款同步和 Rebalance。
- Policy Data 中原始历史保留两次转账。
- 两次转账样本少于 5 笔，因此不会自动排除异常值。
- profile 仅影响流动性策略，不成为资金授权。
- 所有链上操作均有 CAW Pact 约束。
