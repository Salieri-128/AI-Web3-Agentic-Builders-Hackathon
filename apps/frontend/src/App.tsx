import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { ProposalCard } from "./components/ProposalCard";
import { StatusPanel } from "./components/StatusPanel";
import { AuditLog, ChatResponse, fetchProfile, fetchStatus, Profile, Proposal, sendChat, StatusResponse } from "./api";

function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [messages, setMessages] = useState<ChatTurn[]>([
    {
      role: "agent",
      content:
        "I am a policy-controlled treasury agent. Stage 1 supports local memory, CAW read-only audit logs, and proposal-only treasury actions.",
    },
  ]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refreshStatus();
  }, []);

  async function refreshStatus() {
    try {
      setStatus(await fetchStatus());
      setProfile(await fetchProfile());
      setError(null);
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Backend status failed");
    }
  }

  async function handleSend(message: string) {
    setIsSending(true);
    setError(null);
    setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const response: ChatResponse = await sendChat(message);
      setMessages((current) => [
        ...current,
        {
          role: "agent",
          content: response.reply,
          cawUsed: response.caw_used,
          memoryUpdated: response.memory_updated,
        },
      ]);
      setProposal(response.proposal);
      setAuditLogs(response.audit_logs);
      setProfile(response.profile);
      await refreshStatus();
    } catch (currentError) {
      const messageText = currentError instanceof Error ? currentError.message : "Chat request failed";
      setError(messageText);
      setMessages((current) => [...current, { role: "agent", content: messageText }]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <h1>Agentic Treasury Demo</h1>
          <p>Powered by Cobo Agentic Wallet</p>
        </div>
        <button className="secondary-button" onClick={refreshStatus}>
          Refresh Status
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="workspace-grid">
        <ChatPanel messages={messages} isSending={isSending} onSend={handleSend} />

        <section className="panel result-panel" aria-label="Proposal and audit result panel">
          <div className="panel-heading">
            <span>Proposal / Result Panel</span>
            <strong>Execution Disabled in Stage 1</strong>
          </div>
          {proposal ? <ProposalCard proposal={proposal} /> : <p className="empty-state">No proposal generated yet.</p>}

          <div className="audit-section">
            <h2>Audit Logs</h2>
            {auditLogs.length > 0 ? (
              <ul className="audit-list">
                {auditLogs.map((log, index) => (
                  <li key={`${log.request_id ?? "log"}-${index}`}>
                    <span>{log.action ?? "audit_log"}</span>
                    <small>{log.result ?? log.reason ?? "read-only result"}</small>
                    {log.created_at && <time>{log.created_at}</time>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-state">No audit logs loaded.</p>
            )}
          </div>
        </section>

        <aside className="side-column">
          <StatusPanel status={status} />
          <MemoryPanel profile={profile} />
        </aside>
      </section>
    </main>
  );
}

export default App;
