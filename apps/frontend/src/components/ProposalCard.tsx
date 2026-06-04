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
        {proposal.chain_id && (
          <div>
            <dt>chain_id</dt>
            <dd>{proposal.chain_id}</dd>
          </div>
        )}
        <div>
          <dt>execution_enabled</dt>
          <dd>{String(proposal.execution_enabled)}</dd>
        </div>
      </dl>
      <p>{proposal.reason}</p>
      {proposal.pact_submission && (
        <pre className="json-block">{JSON.stringify(proposal.pact_submission, null, 2)}</pre>
      )}
      {proposal.execution_result && (
        <pre className="json-block">{JSON.stringify(proposal.execution_result, null, 2)}</pre>
      )}
      <strong className="disabled-badge">Execution Disabled in Stage 1</strong>
    </article>
  );
}
