import { LocalPact, TreasuryState } from "../api";

type TreasuryPanelProps = {
  treasury: TreasuryState | null;
  isBusy: boolean;
  onInitialize: () => void;
  onRebalance: () => void;
  onApprovePact: (pactId: string) => void;
  onSubmitAavePact: () => void;
  onClaimAaveFaucet: (pactId: string) => void;
  onSupplyAave: (pactId: string) => void;
  onWithdrawAave: (pactId: string) => void;
};

export function TreasuryPanel({
  treasury,
  isBusy,
  onInitialize,
  onRebalance,
  onApprovePact,
  onSubmitAavePact,
  onClaimAaveFaucet,
  onSupplyAave,
  onWithdrawAave,
}: TreasuryPanelProps) {
  const internalPact = treasury?.pacts.find((pact) => pact.pact_type === "internal_agent_rebalance");
  const cawPactId = internalPact?.caw_pact_id ?? internalPact?.pact_id;

  return (
    <section className="panel compact-panel" aria-label="Strategy wallet panel">
      <div className="panel-heading">
        <span>Strategy Wallet</span>
        <strong>{treasury?.mode?.includes("sepolia_real") ? "Real Sepolia" : "Local Demo"}</strong>
      </div>

      <div className="action-row">
        <button className="secondary-button" disabled={isBusy} onClick={onInitialize} type="button">
          Initialize Strategy
        </button>
        <button className="secondary-button" disabled={isBusy} onClick={onRebalance} type="button">
          Daily Rebalance
        </button>
      </div>

      <div className="action-row aave-actions">
        <button className="secondary-button" disabled={isBusy} onClick={onSubmitAavePact} type="button">
          Submit Aave Pact
        </button>
        <button
          className="secondary-button"
          disabled={isBusy || !cawPactId}
          onClick={() => cawPactId && onClaimAaveFaucet(cawPactId)}
          type="button"
        >
          Claim 100 USDC
        </button>
        <button
          className="secondary-button"
          disabled={isBusy || !cawPactId}
          onClick={() => cawPactId && onSupplyAave(cawPactId)}
          type="button"
        >
          Supply 10 USDC
        </button>
        <button
          className="secondary-button"
          disabled={isBusy || !cawPactId}
          onClick={() => cawPactId && onWithdrawAave(cawPactId)}
          type="button"
        >
          Withdraw 10 USDC
        </button>
      </div>

      {treasury ? (
        <>
          {treasury.wallet_status?.reason && <p className="empty-state">{treasury.wallet_status.reason}</p>}
          <dl className="status-list">
            <div>
              <dt>wallet</dt>
              <dd>{treasury.balances.wallet} {treasury.asset}</dd>
            </div>
            <div>
              <dt>yield</dt>
              <dd>{treasury.balances.yield ?? treasury.balances.aave ?? "0"} {treasury.asset}</dd>
            </div>
            <div>
              <dt>total</dt>
              <dd>{treasury.balances.total} {treasury.asset}</dd>
            </div>
            <div>
              <dt>recommended</dt>
              <dd>{treasury.recommendation.recommended_liquidity} {treasury.asset}</dd>
            </div>
          </dl>

          <h2 className="subheading">7 Day Transfer Stats</h2>
          <dl className="status-list">
            <div>
              <dt>count</dt>
              <dd>{treasury.transfer_stats_7d.weekly_transfer_count}</dd>
            </div>
            <div>
              <dt>sum</dt>
              <dd>{treasury.transfer_stats_7d.weekly_transfer_sum} {treasury.asset}</dd>
            </div>
            <div>
              <dt>max single</dt>
              <dd>{treasury.transfer_stats_7d.weekly_max_single_amount} {treasury.asset}</dd>
            </div>
          </dl>

          <h2 className="subheading">Local Pacts</h2>
          {treasury.pacts.length ? (
            <ul className="pact-list">
              {treasury.pacts.map((pact) => (
                <PactItem key={pact.pact_id} pact={pact} onApprovePact={onApprovePact} isBusy={isBusy} />
              ))}
            </ul>
          ) : (
            <p className="empty-state">No local pacts created yet.</p>
          )}
        </>
      ) : (
        <p className="empty-state">No strategy wallet state loaded.</p>
      )}
    </section>
  );
}

function PactItem({
  pact,
  isBusy,
  onApprovePact,
}: {
  pact: LocalPact;
  isBusy: boolean;
  onApprovePact: (pactId: string) => void;
}) {
  const canApprove = pact.status === "pending_owner_approval";
  return (
    <li>
      <div className="pact-title">
        <span>{pact.pact_type}</span>
        <small>{pact.status}</small>
      </div>
      <code>{pact.pact_id}</code>
      <small>{pact.reason}</small>
      {canApprove && (
        <button className="secondary-button" disabled={isBusy} onClick={() => onApprovePact(pact.pact_id)} type="button">
          Approve
        </button>
      )}
    </li>
  );
}
