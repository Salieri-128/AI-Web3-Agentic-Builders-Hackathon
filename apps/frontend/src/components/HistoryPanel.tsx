import { useState } from "react";
import { ChatResponse } from "../api";

export type HistoryItem = {
  id: string;
  prompt: string;
  createdAt: string;
  result: ChatResponse | { reply: string };
};

type HistoryPanelProps = {
  items: HistoryItem[];
};

export function HistoryPanel({ items }: HistoryPanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(items[0]?.id ?? null);
  const selected = items.find((item) => item.id === selectedId) ?? items[0];

  return (
    <section className="history-layout" aria-label="Interaction history">
      <aside className="history-list">
        {items.length ? (
          items.map((item) => (
            <button
              className={item.id === selected?.id ? "active" : ""}
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              type="button"
            >
              <span>{item.prompt}</span>
              <small>{formatDate(item.createdAt)}</small>
            </button>
          ))
        ) : (
          <p className="empty-state">No interactions yet.</p>
        )}
      </aside>

      <section className="history-detail">
        {selected ? (
          <>
            <div className="panel-heading">
              <span>{selected.prompt}</span>
              <strong>{formatDate(selected.createdAt)}</strong>
            </div>
            <h2>Prompt</h2>
            <p>{selected.prompt}</p>
            <h2>AI Result</h2>
            <p>{selected.result.reply}</p>
            <pre className="json-block">{JSON.stringify(selected.result, null, 2)}</pre>
          </>
        ) : (
          <p className="empty-state">Select a record to inspect the full result.</p>
        )}
      </section>
    </section>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}
