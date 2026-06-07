import { Proposal } from "../api";

type ProposalCardProps = {
  proposal: Proposal;
};

export function ProposalCard({ proposal }: ProposalCardProps) {
  const title = proposal.type ?? proposal.pact_type ?? "pact";
  const asset = proposal.asset ?? String(proposal.scope?.asset ?? "n/a");
  const amount = proposal.amount ?? String(proposal.scope?.max_single_amount ?? proposal.scope?.max_amount ?? "n/a");
  const destination = proposal.destination ?? String(proposal.scope?.destination_address ?? "internal only");
  const chainId = proposal.chain_id ?? String(proposal.scope?.chain_id ?? "");

  return (
    <article className="proposal-card">
      <div className="proposal-topline">
        <h2>{title}</h2>
        <span>{proposal.status}</span>
      </div>
      <dl>
        {proposal.pact_id && (
          <div>
            <dt>pact_id</dt>
            <dd>{proposal.pact_id}</dd>
          </div>
        )}
        <div>
          <dt>asset</dt>
          <dd>{asset}</dd>
        </div>
        <div>
          <dt>amount</dt>
          <dd>{amount}</dd>
        </div>
        <div>
          <dt>destination</dt>
          <dd>{destination}</dd>
        </div>
        {chainId && (
          <div>
            <dt>chain_id</dt>
            <dd>{chainId}</dd>
          </div>
        )}
        <div>
          <dt>execution_enabled</dt>
          <dd>{String(Boolean(proposal.execution_enabled))}</dd>
        </div>
      </dl>
      <p>{proposal.reason}</p>
      {proposal.scope && <pre className="json-block">{JSON.stringify(proposal.scope, null, 2)}</pre>}
      {proposal.pact_submission && (
        <pre className="json-block">{JSON.stringify(proposal.pact_submission, null, 2)}</pre>
      )}
      {proposal.execution_result && (
        <pre className="json-block">{JSON.stringify(proposal.execution_result, null, 2)}</pre>
      )}
      <strong className="disabled-badge">Requires Pact Approval</strong>
    </article>
  );
}
