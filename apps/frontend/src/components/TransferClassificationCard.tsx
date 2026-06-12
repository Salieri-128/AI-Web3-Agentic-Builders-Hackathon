import { TransferClassificationProposal } from "../api";

type TransferClassificationCardProps = {
  proposal: TransferClassificationProposal;
  isBusy: boolean;
  onConfirm: (proposalId: string) => Promise<void>;
  onReject: (proposalId: string) => Promise<void>;
};

export function TransferClassificationCard({
  proposal,
  isBusy,
  onConfirm,
  onReject,
}: TransferClassificationCardProps) {
  const label = proposal.classification === "one_off" ? "一次性大额" : "经常性转账";
  return (
    <article className="classification-card" aria-label="Transfer classification proposal">
      <div className="planner-card-heading">
        <div>
          <span>History classification</span>
          <h2>将这笔转账标记为{label}</h2>
        </div>
        <b>等待确认</b>
      </div>

      <div className="classification-event">
        <strong>{proposal.event.amount} WBTC</strong>
        <span>{formatDate(proposal.event.created_at)}</span>
        <code>{shortAddress(proposal.event.destination)}</code>
      </div>

      <div className="classification-impact">
        <div>
          <span>经常性总额</span>
          <strong>
            {proposal.statistics_before.recurring_transfer_sum} →{" "}
            {proposal.statistics_after.recurring_transfer_sum} WBTC
          </strong>
        </div>
        <div>
          <span>经常性 P90</span>
          <strong>
            {proposal.statistics_before.recurring_p90_transfer_amount} →{" "}
            {proposal.statistics_after.recurring_p90_transfer_amount} WBTC
          </strong>
        </div>
        <div>
          <span>排除笔数</span>
          <strong>
            {proposal.statistics_before.excluded_transfer_count} →{" "}
            {proposal.statistics_after.excluded_transfer_count}
          </strong>
        </div>
      </div>

      <p className="planner-boundary-note">{proposal.safety_boundary}</p>

      <div className="memory-proposal-actions">
        <button
          className="primary-action-button"
          disabled={isBusy}
          onClick={() => void onConfirm(proposal.proposal_id)}
          type="button"
        >
          {isBusy ? "Applying..." : "确认分类"}
        </button>
        <button
          className="secondary-button"
          disabled={isBusy}
          onClick={() => void onReject(proposal.proposal_id)}
          type="button"
        >
          保持自动判断
        </button>
      </div>
    </article>
  );
}

function formatDate(value?: string) {
  if (!value) {
    return "时间未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function shortAddress(value?: string) {
  if (!value) {
    return "address unavailable";
  }
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}
