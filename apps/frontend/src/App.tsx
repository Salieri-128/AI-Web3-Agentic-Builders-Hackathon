import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { ProposalCard } from "./components/ProposalCard";
import { StatusPanel } from "./components/StatusPanel";
import { WalletPanel } from "./components/WalletPanel";
import {
  AuditLog,
  ChatResponse,
  fetchProfile,
  fetchStatus,
  fetchWalletStatus,
  Profile,
  Proposal,
  sendChat,
  StatusResponse,
  WalletStatus,
} from "./api";

function App() {
  const [activeTab, setActiveTab] = useState<"chat" | "profile">("chat");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [wallet, setWallet] = useState<WalletStatus | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refreshStatus();
  }, []);

  async function refreshStatus() {
    try {
      setStatus(await fetchStatus());
      setProfile(await fetchProfile());
      setWallet(await fetchWalletStatus());
      setError(null);
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Backend status failed");
    }
  }

  async function handleSend(message: string) {
    setIsSending(true);
    setError(null);
    setMessages([{ role: "user", content: message }]);
    try {
      const response: ChatResponse = await sendChat(message);
      setMessages([
        { role: "user", content: message },
        {
          role: "agent",
          content: response.reply,
          llmUsed: response.llm_used,
          cawUsed: response.caw_used,
          memoryUpdated: response.memory_updated,
        },
      ]);
      setProposal(response.proposal);
      setWallet(response.wallet ?? wallet);
      setAuditLogs(response.audit_logs);
      setProfile(response.profile);
      await refreshStatus();
    } catch (currentError) {
      const messageText = currentError instanceof Error ? currentError.message : "Chat request failed";
      setError(messageText);
      setMessages([
        { role: "user", content: message },
        { role: "agent", content: messageText },
      ]);
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

      <nav className="tab-bar" aria-label="Primary navigation">
        <button className={activeTab === "chat" ? "active" : ""} onClick={() => setActiveTab("chat")} type="button">
          Chat
        </button>
        <button
          className={activeTab === "profile" ? "active" : ""}
          onClick={() => setActiveTab("profile")}
          type="button"
        >
          Profile
        </button>
      </nav>

      {error && <div className="error-banner">{error}</div>}

      {activeTab === "chat" ? (
        <section className="chat-tab-layout">
          <ChatPanel messages={messages} isSending={isSending} onSend={handleSend} />
          <section className="panel result-panel" aria-label="Proposal and audit result panel">
            <div className="panel-heading">
              <span>Current Result</span>
              <strong>CAW Guarded</strong>
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
                <p className="empty-state">No audit logs loaded for the current request.</p>
              )}
            </div>
          </section>
        </section>
      ) : (
        <section className="profile-tab-layout">
          <StatusPanel status={status} />
          <WalletPanel wallet={wallet} />
          <MemoryPanel profile={profile} />
        </section>
      )}
    </main>
  );
}

export default App;
