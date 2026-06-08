import { useMemo, useState } from "react";
import { TreasuryState, WalletStatus } from "../api";

type PortfolioPanelProps = {
  wallet: WalletStatus | null;
  treasury: TreasuryState | null;
};

type AssetRow = {
  chain: string;
  symbol: string;
  label: string;
  amount: number;
  priceUsd: number;
  source: string;
};

const PRICE_USD: Record<string, number> = {
  SETH: 3500,
  USDC: 1,
  aUSDC: 1,
  WBTC: 69000,
  aWBTC: 69000,
};

export function PortfolioPanel({ wallet, treasury }: PortfolioPanelProps) {
  const assets = useMemo(() => buildAssets(wallet, treasury), [wallet, treasury]);
  const chains = Array.from(new Set(assets.map((asset) => asset.chain)));
  const [activeChain, setActiveChain] = useState(chains[0] ?? "SETH");
  const visibleAssets = assets.filter((asset) => asset.chain === activeChain);
  const chainTotalUsd = visibleAssets.reduce((sum, asset) => sum + asset.amount * asset.priceUsd, 0);
  const walletAddress = treasury?.aave?.wallet_address;

  return (
    <section className="portfolio-layout" aria-label="Portfolio">
      <div className="portfolio-summary">
        <div>
          <span>Current Chain</span>
          <h2>{activeChain}</h2>
          {walletAddress && <p>{walletAddress}</p>}
        </div>
        <strong>{formatUsd(chainTotalUsd)}</strong>
      </div>

      <nav className="chain-switcher" aria-label="Chain selector">
        {chains.map((chain) => (
          <button className={chain === activeChain ? "active" : ""} key={chain} onClick={() => setActiveChain(chain)} type="button">
            {chain}
          </button>
        ))}
      </nav>

      <section className="asset-list" aria-label="Assets">
        {visibleAssets.length ? (
          visibleAssets.map((asset) => (
            <article className="asset-row" key={`${asset.chain}-${asset.symbol}-${asset.source}`}>
              <div>
                <span className="asset-symbol">{asset.symbol}</span>
                <small>{asset.label}</small>
              </div>
              <div className="asset-amount">
                <strong>{formatAmount(asset.amount)}</strong>
                <small>{formatUsd(asset.amount * asset.priceUsd)}</small>
              </div>
            </article>
          ))
        ) : (
          <p className="empty-state">No assets loaded for this chain.</p>
        )}
      </section>
    </section>
  );
}

function buildAssets(wallet: WalletStatus | null, treasury: TreasuryState | null): AssetRow[] {
  const assets: AssetRow[] = [];

  for (const balance of wallet?.balances ?? []) {
    const rawSymbol = String(balance.token_id ?? balance.symbol ?? "token");
    const symbol = rawSymbol === "ETH" ? "SETH" : rawSymbol;
    const chain = String(balance.chain_id ?? "unknown");
    const amount = Number(balance.balance ?? balance.available ?? balance.amount ?? balance.total ?? 0);
    if (!Number.isFinite(amount) || amount <= 0) {
      continue;
    }
    assets.push({
      chain,
      symbol,
      label: "Wallet balance",
      amount,
      priceUsd: PRICE_USD[symbol] ?? 0,
      source: "wallet",
    });
  }

  const strategyAsset = treasury?.aave?.asset ?? treasury?.asset ?? "WBTC";
  const strategyAToken = treasury?.aave?.a_token_asset ?? `a${strategyAsset}`;

  const walletStrategyBalance = Number(treasury?.aave?.wallet_balance ?? treasury?.balances.wallet ?? 0);
  if (Number.isFinite(walletStrategyBalance) && walletStrategyBalance > 0) {
    upsertAsset(assets, {
      chain: treasury?.chain_id ?? "SETH",
      symbol: strategyAsset,
      label: "Wallet balance",
      amount: walletStrategyBalance,
      priceUsd: PRICE_USD[strategyAsset] ?? 0,
      source: "aave-wallet-asset",
    });
  }

  const aaveStrategyBalance = Number(treasury?.aave?.aave_balance ?? treasury?.balances.yield ?? 0);
  if (Number.isFinite(aaveStrategyBalance) && aaveStrategyBalance > 0) {
    assets.push({
      chain: treasury?.chain_id ?? "SETH",
      symbol: strategyAToken,
      label: "Aave supplied balance",
      amount: aaveStrategyBalance,
      priceUsd: PRICE_USD[strategyAToken] ?? PRICE_USD[strategyAsset] ?? 0,
      source: "aave-yield",
    });
  }

  return assets.sort((left, right) => left.symbol.localeCompare(right.symbol));
}

function upsertAsset(assets: AssetRow[], asset: AssetRow) {
  const existing = assets.find((item) => item.chain === asset.chain && item.symbol === asset.symbol && item.source === asset.source);
  if (existing) {
    existing.amount = asset.amount;
  } else {
    assets.push(asset);
  }
}

function formatAmount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(value);
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", { currency: "USD", maximumFractionDigits: 2, style: "currency" }).format(value);
}
