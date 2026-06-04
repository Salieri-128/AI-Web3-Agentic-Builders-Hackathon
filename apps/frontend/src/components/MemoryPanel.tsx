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
        <Row label="cash_buffer_usdc" value={String(preferences?.cash_buffer_usdc ?? "not set")} />
        <Row label="prefers_low_gas" value={String(habits?.prefers_low_gas ?? "unknown")} />
        <Row
          label="requires_confirmation"
          value={String(habits?.requires_confirmation_before_execution ?? "unknown")}
        />
      </dl>

      <div className="notes-block">
        <h2>notes</h2>
        {profile?.notes && profile.notes.length > 0 ? (
          <ul>
            {profile.notes.map((note, index) => (
              <li key={`${note}-${index}`}>{note}</li>
            ))}
          </ul>
        ) : (
          <p className="empty-state">No memory notes yet.</p>
        )}
      </div>
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
