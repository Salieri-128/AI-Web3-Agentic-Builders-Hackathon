import { Proposal } from "../api";

type ProposalCardProps = {
  proposal: Proposal;
};

export function ProposalCard({ proposal }: ProposalCardProps) {
  return (
    <article className="proposal-card">
      <div className="proposal-topline">
        <h2>{proposal.type}</h2>
        <span>{proposal.status}</span>
      </div>
      <dl>
        <div>
          <dt>asset</dt>
          <dd>{proposal.asset}</dd>
        </div>
        <div>
          <dt>amount</dt>
          <dd>{proposal.amount}</dd>
        </div>
        <div>
          <dt>destination</dt>
          <dd>{proposal.destination}</dd>
        </div>
        <div>
          <dt>execution_enabled</dt>
          <dd>{String(proposal.execution_enabled)}</dd>
        </div>
      </dl>
      <p>{proposal.reason}</p>
      <strong className="disabled-badge">Execution Disabled in Stage 1</strong>
    </article>
  );
}
