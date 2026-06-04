import { WalletStatus } from "../api";

type WalletPanelProps = {
  wallet: WalletStatus | null;
};

export function WalletPanel({ wallet }: WalletPanelProps) {
  return (
    <section className="panel compact-panel" aria-label="Wallet panel">
      <div className="panel-heading">
        <span>Wallet</span>
        <strong>Observer</strong>
      </div>

      {wallet?.reason && <p className="empty-state">{wallet.reason}</p>}
      {wallet?.wallet ? <KeyValueList value={wallet.wallet} /> : <p className="empty-state">No wallet status loaded.</p>}

      <h2 className="subheading">Balances</h2>
      {wallet?.balances?.length ? (
        <ul className="audit-list">
          {wallet.balances.map((balance, index) => (
            <li key={`${balance.chain_id ?? "chain"}-${balance.token_id ?? "token"}-${index}`}>
              <span>{String(balance.token_id ?? "token")}</span>
              <small>{String(balance.balance ?? balance.available ?? "0")}</small>
              {balance.chain_id && <time>{String(balance.chain_id)}</time>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-state">No balances loaded.</p>
      )}

      <h2 className="subheading">Addresses</h2>
      {wallet?.addresses?.length ? (
        <ul className="audit-list">
          {wallet.addresses.map((address, index) => (
            <li key={`${address.chain_id ?? "chain"}-${index}`}>
              <span>{String(address.chain_id ?? "chain")}</span>
              <small>{String(address.address ?? "address unavailable")}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-state">No addresses loaded.</p>
      )}
    </section>
  );
}

function KeyValueList({ value }: { value: Record<string, string | number | boolean | null> }) {
  return (
    <dl className="status-list">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{String(item)}</dd>
        </div>
      ))}
    </dl>
  );
}
