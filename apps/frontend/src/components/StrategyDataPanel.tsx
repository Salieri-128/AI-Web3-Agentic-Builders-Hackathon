import { Profile, TreasuryState } from "../api";

type StrategyDataPanelProps = {
  profile: Profile | null;
  treasury: TreasuryState | null;
};

type DataRow = {
  label: string;
  value: string;
  note: string;
};

export function StrategyDataPanel({ profile, treasury }: StrategyDataPanelProps) {
  const asset = treasury?.asset ?? "WBTC";
  const totalBalance = treasury?.balances.total ?? "0";
  const recommendedLiquidity = treasury?.recommendation.recommended_liquidity ?? "0";
  const targetYield = treasury?.recommendation.target_yield_balance ?? treasury?.recommendation.target_aave_balance ?? "0";
  const liquidityRatio = getRatioLabel(recommendedLiquidity, totalBalance);
  const candidateRows = buildCandidateRows(treasury);
  const memoryRows = buildMemoryRows(profile);
  const transferRows = buildTransferRows(treasury, asset);
  const strategyRows = buildStrategyRows(treasury, asset);

  return (
    <section className="strategy-data-layout" aria-label="Strategy data">
      <section className="panel strategy-data-summary">
        <div className="panel-heading">
          <span>Strategy Data</span>
          <strong>{asset}</strong>
        </div>

        <div className="formula-block">
          <span>保留流动性计算公式</span>
          <code>{treasury?.recommendation.formula ?? "等待后端策略数据"}</code>
        </div>

        <div className="strategy-data-kpis">
          <div>
            <span>建议保留</span>
            <strong>
              {recommendedLiquidity} {asset}
            </strong>
            <small>{liquidityRatio} of total</small>
          </div>
          <div>
            <span>放入 Aave</span>
            <strong>
              {targetYield} {asset}
            </strong>
            <small>目标生息仓位</small>
          </div>
          <div>
            <span>总资金</span>
            <strong>
              {totalBalance} {asset}
            </strong>
            <small>钱包和 Aave 合计</small>
          </div>
        </div>
      </section>

      <section className="strategy-data-grid">
        <DataCard title="公式候选值" rows={candidateRows} emptyText="暂无候选值数据。" />
        <DataCard title="用户画像 / Memory" rows={memoryRows} emptyText="暂无用户画像数据。" />
        <DataCard title="历史转账数据" rows={transferRows} emptyText="暂无转账统计数据。" />
        <DataCard title="策略参数" rows={strategyRows} emptyText="暂无策略参数。" />
      </section>
    </section>
  );
}

function DataCard({ title, rows, emptyText }: { title: string; rows: DataRow[]; emptyText: string }) {
  return (
    <article className="strategy-data-card">
      <h2>{title}</h2>
      {rows.length ? (
        <dl>
          {rows.map((row) => (
            <div key={row.label}>
              <dt>
                <span>{row.label}</span>
                <small>{row.note}</small>
              </dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="empty-state">{emptyText}</p>
      )}
    </article>
  );
}

function buildCandidateRows(treasury: TreasuryState | null): DataRow[] {
  const candidates = treasury?.recommendation.candidates ?? {};
  const labels: Record<string, { label: string; note: string }> = {
    user_floor: { label: "最低保留", note: "用户设置与策略基础缓冲的较大值" },
    min_liquidity_ratio: { label: "最低比例", note: "总资金乘以最小流动性比例" },
    flow_horizon: { label: "流出需求", note: "日均流出乘以流动性周期和风险系数" },
    p95_transfer: { label: "P95 单笔", note: "历史 P95 转账额乘以单笔系数" },
    economic_batch: { label: "经济批量", note: "综合取款 Gas、转账频率和 Aave APY" },
  };

  return Object.entries(candidates).map(([key, value]) => ({
    label: labels[key]?.label ?? key,
    value: `${value} ${treasury?.asset ?? ""}`.trim(),
    note: labels[key]?.note ?? "参与 max 计算的候选值",
  }));
}

function buildMemoryRows(profile: Profile | null): DataRow[] {
  const preferences = profile?.user_preferences;
  const habits = profile?.transaction_habits;
  return [
    {
      label: "风险偏好",
      value: preferences?.risk_level ?? "未设置",
      note: "影响策略解释和后续风控倾向",
    },
    {
      label: "偏好资产",
      value: formatList(preferences?.preferred_assets),
      note: "Agent 推荐时优先考虑",
    },
    {
      label: "拒绝资产",
      value: formatList(preferences?.blocked_assets),
      note: "Agent 应避免推荐",
    },
    {
      label: "用户确认",
      value: habits?.requires_confirmation_before_execution === false ? "可在授权内执行" : "执行前需要确认",
      note: "不等于资金授权，最终仍受 Pact 约束",
    },
    {
      label: "低 Gas 偏好",
      value: habits?.prefers_low_gas ? "是" : "否 / 未设置",
      note: "影响再平衡频率倾向",
    },
  ];
}

function buildTransferRows(treasury: TreasuryState | null, asset: string): DataRow[] {
  const stats = treasury?.transfer_stats_7d;
  if (!stats) {
    return [];
  }
  return [
    {
      label: "转账次数",
      value: String(stats.weekly_transfer_count),
      note: "当前统计窗口内的外部转账次数",
    },
    {
      label: "转账总额",
      value: `${stats.weekly_transfer_sum} ${asset}`,
      note: "用于估算短期流动性需求",
    },
    {
      label: "最大单笔",
      value: `${stats.weekly_max_single_amount} ${asset}`,
      note: "用于保留可覆盖单笔需求的资金",
    },
    {
      label: "平均单笔",
      value: `${stats.weekly_avg_transfer_amount} ${asset}`,
      note: "辅助理解近期资金使用节奏",
    },
  ];
}

function buildStrategyRows(treasury: TreasuryState | null, asset: string): DataRow[] {
  const strategy = treasury?.strategy ?? {};
  const rows: Array<[string, string, string]> = [
    ["base_buffer", "基础缓冲", "最低保留资金"],
    ["liquidity_horizon_days", "流动性周期", "希望钱包覆盖的未来转账天数"],
    ["min_liquidity_ratio", "最小流动性比例", "总资金乘以该比例"],
    ["risk_multiplier", "风险系数", "放大近期转账总额"],
    ["single_tx_multiplier", "单笔系数", "放大最大单笔转账"],
    ["min_rebalance_amount", "最小调仓金额", "低于该值不触发调仓"],
    ["aave_apy", "Aave APY", "用于估算收益是否覆盖 Gas"],
    ["max_holding_days", "最长持有期", "收益评估采用的持有时间上限"],
    ["transfer_history_days", "统计窗口", "用于计算转账流出习惯"],
  ];

  return rows
    .filter(([key]) => strategy[key] !== undefined)
    .map(([key, label, note]) => ({
      label,
      value: String(strategy[key]),
      note,
    }));
}

function getRatioLabel(part: string, total: string) {
  const partAmount = Number(part);
  const totalAmount = Number(total);
  if (!Number.isFinite(partAmount) || !Number.isFinite(totalAmount) || totalAmount <= 0) {
    return "0%";
  }
  return `${((partAmount / totalAmount) * 100).toFixed(0)}%`;
}

function formatList(value?: string[]) {
  return value?.length ? value.join(", ") : "未设置";
}
