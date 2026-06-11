import { Profile } from "../api";

type MemoryPanelProps = {
  profile: Profile | null;
};

export function MemoryPanel({ profile }: MemoryPanelProps) {
  const preferences = profile?.user_preferences;
  const habits = profile?.transaction_habits;

  return (
    <section className="panel compact-panel" aria-label="Memory panel">
      <div className="panel-heading">
        <span>Memory</span>
        <strong>Profile</strong>
      </div>
      <dl className="status-list">
        <Row label="risk_level" value={preferences?.risk_level ?? "unknown"} />
        <Row label="liquidity_floor" value={String(preferences?.liquidity_floor ?? "not set")} />
        <Row
          label="liquidity_horizon_days"
          value={String(preferences?.liquidity_horizon_days ?? "system default")}
        />
        <Row label="prefers_low_gas" value={String(habits?.prefers_low_gas ?? "unknown")} />
      </dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
