import { StatusResponse } from "../api";

type StatusPanelProps = {
  status: StatusResponse | null;
};

export function StatusPanel({ status }: StatusPanelProps) {
  return (
    <section className="panel compact-panel" aria-label="Status panel">
      <div className="panel-heading">
        <span>Status</span>
        <strong>CAW</strong>
      </div>
      <dl className="status-list">
        <Row label="backend" value={status?.backend ?? "loading"} />
        <Row label="agent" value={status?.agent ?? "loading"} />
        <Row label="caw_configured" value={status ? String(status.caw_configured) : "loading"} />
        <Row label="llm_configured" value={status ? String(status.llm_configured) : "loading"} />
        <Row label="memory_loaded" value={status ? String(status.memory_loaded) : "loading"} />
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
