import { MemoryProposal } from "../api";

type MemoryProposalCardProps = {
  proposal: MemoryProposal;
  isBusy: boolean;
  onConfirm: (proposalId: string) => Promise<void>;
  onReject: (proposalId: string) => Promise<void>;
};

const FIELD_LABELS: Record<string, string> = {
  risk_level: "风险等级",
  liquidity_floor: "最低保留",
  liquidity_horizon_days: "覆盖天数",
  prefers_low_gas: "低 Gas 偏好",
};

const CANDIDATE_LABELS: Record<string, string> = {
  user_floor: "用户最低保留",
  min_liquidity_ratio: "最低安全比例",
  flow_horizon: "历史流出需求",
  p95_transfer: "P95 单笔需求",
  economic_batch: "Gas 经济批量",
};

export function MemoryProposalCard({
  proposal,
  isBusy,
  onConfirm,
  onReject,
}: MemoryProposalCardProps) {
  const impact = proposal.liquidity_impact;
  const candidateChanges = Object.keys(impact.after.candidates).filter(
    (key) => impact.before.candidates[key] !== impact.after.candidates[key],
  );

  return (
    <article className="memory-proposal-card" aria-label="Liquidity profile proposal">
      <div className="memory-proposal-heading">
        <div>
          <span>Memory proposal</span>
          <h2>画像将如何改变流动性保留</h2>
        </div>
        <b>等待确认</b>
      </div>

      <div className="memory-impact-hero">
        <div>
          <span>建议保留</span>
          <strong>
            {impact.before.recommended_liquidity} → {impact.after.recommended_liquidity} {impact.asset}
          </strong>
        </div>
        <div>
          <span>Aave 目标仓位</span>
          <strong>
            {impact.before.target_yield_balance} → {impact.after.target_yield_balance} {impact.asset}
          </strong>
        </div>
      </div>

      <dl className="memory-change-list">
        {proposal.changes.map((change) => (
          <div key={change.field}>
            <dt>{FIELD_LABELS[change.field] ?? change.field}</dt>
            <dd>
              {formatValue(change.before)} <span>→</span> {formatValue(change.after)}
            </dd>
          </div>
        ))}
      </dl>

      {candidateChanges.length > 0 && (
        <div className="candidate-impact-list">
          <span>受影响的公式输入</span>
          {candidateChanges.map((key) => (
            <p key={key}>
              <b>{CANDIDATE_LABELS[key] ?? key}</b>
              <span>{impact.before.candidates[key]} → {impact.after.candidates[key]} {impact.asset}</span>
            </p>
          ))}
        </div>
      )}

      <p className="memory-boundary-note">
        此变更只影响资金策略建议，不会修改 CAW Pact、额度或地址权限。
      </p>

      <div className="memory-proposal-actions">
        <button
          className="primary-action-button"
          disabled={isBusy}
          onClick={() => void onConfirm(proposal.proposal_id)}
          type="button"
        >
          {isBusy ? "Applying..." : "确认并应用"}
        </button>
        <button
          className="secondary-button"
          disabled={isBusy}
          onClick={() => void onReject(proposal.proposal_id)}
          type="button"
        >
          拒绝变更
        </button>
      </div>
    </article>
  );
}

function formatValue(value: string | number | boolean | null) {
  if (value === null || value === "") {
    return "未设置";
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value);
}
