import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { HistoryItem, HistoryPanel } from "./components/HistoryPanel";
import { PortfolioPanel } from "./components/PortfolioPanel";
import { TreasuryPanel } from "./components/TreasuryPanel";
import {
  AuditLog,
  approveTreasuryPact,
  ChatResponse,
  claimAaveFaucet,
  fetchProfile,
  fetchStatus,
  fetchTreasuryState,
  fetchWalletStatus,
  initializeTreasury,
  Profile,
  Proposal,
  rebalanceTreasury,
  sendChat,
  StatusResponse,
  submitAavePact,
  supplyAave,
  TreasuryState,
  WalletStatus,
  withdrawAave,
} from "./api";

function App() {
  const [activeTab, setActiveTab] = useState<"chat" | "portfolio" | "strategy" | "history">("chat");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [wallet, setWallet] = useState<WalletStatus | null>(null);
  const [treasury, setTreasury] = useState<TreasuryState | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isTreasuryBusy, setIsTreasuryBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refreshStatus();
  }, []);

  async function refreshStatus() {
    try {
      setStatus(await fetchStatus());
      setProfile(await fetchProfile());
      setWallet(await fetchWalletStatus());
      setTreasury(await fetchTreasuryState());
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
      setTreasury(await fetchTreasuryState());
      setAuditLogs(response.audit_logs);
      setProfile(response.profile);
      setHistory((items) => [
        {
          id: `${Date.now()}`,
          prompt: message,
          createdAt: new Date().toISOString(),
          result: response,
        },
        ...items,
      ]);
      await refreshStatus();
    } catch (currentError) {
      const messageText = currentError instanceof Error ? currentError.message : "Chat request failed";
      setError(messageText);
      setMessages([
        { role: "user", content: message },
        { role: "agent", content: messageText },
      ]);
      setHistory((items) => [
        {
          id: `${Date.now()}`,
          prompt: message,
          createdAt: new Date().toISOString(),
          result: { reply: messageText },
        },
        ...items,
      ]);
    } finally {
      setIsSending(false);
    }
  }

  async function handleInitializeTreasury() {
    setIsTreasuryBusy(true);
    setError(null);
    try {
      setTreasury(await initializeTreasury("1000"));
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Treasury initialization failed");
    } finally {
      setIsTreasuryBusy(false);
    }
  }

  async function handleRebalanceTreasury() {
    setIsTreasuryBusy(true);
    setError(null);
    try {
      const result = await rebalanceTreasury();
      setTreasury((result.treasury as TreasuryState | undefined) ?? (await fetchTreasuryState()));
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Treasury rebalance failed");
    } finally {
      setIsTreasuryBusy(false);
    }
  }

  async function handleApproveTreasuryPact(pactId: string) {
    setIsTreasuryBusy(true);
    setError(null);
    try {
      await approveTreasuryPact(pactId);
      setTreasury(await fetchTreasuryState());
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Pact approval failed");
    } finally {
      setIsTreasuryBusy(false);
    }
  }

  async function handleSubmitAavePact() {
    await runTreasuryAction(async () => {
      await submitAavePact("100");
    }, "Aave pact submission failed");
  }

  async function handleClaimAaveFaucet(pactId: string) {
    await runTreasuryAction(async () => {
      await claimAaveFaucet(pactId, "100");
    }, "Aave faucet claim failed");
  }

  async function handleSupplyAave(pactId: string) {
    await runTreasuryAction(async () => {
      await supplyAave(pactId, "10");
    }, "Aave supply failed");
  }

  async function handleWithdrawAave(pactId: string) {
    await runTreasuryAction(async () => {
      await withdrawAave(pactId, "10");
    }, "Aave withdraw failed");
  }

  async function runTreasuryAction(action: () => Promise<void>, errorMessage: string) {
    setIsTreasuryBusy(true);
    setError(null);
    try {
      await action();
      setTreasury(await fetchTreasuryState());
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : errorMessage);
    } finally {
      setIsTreasuryBusy(false);
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
          className={activeTab === "portfolio" ? "active" : ""}
          onClick={() => setActiveTab("portfolio")}
          type="button"
        >
          Portfolio
        </button>
        <button
          className={activeTab === "strategy" ? "active" : ""}
          onClick={() => setActiveTab("strategy")}
          type="button"
        >
          Strategy
        </button>
        <button
          className={activeTab === "history" ? "active" : ""}
          onClick={() => setActiveTab("history")}
          type="button"
        >
          History
        </button>
      </nav>

      {error && <div className="error-banner">{error}</div>}

      {activeTab === "chat" && (
        <section className="chat-tab-layout">
          <ChatPanel messages={messages} isSending={isSending} onSend={handleSend} />
        </section>
      )}

      {activeTab === "portfolio" && <PortfolioPanel wallet={wallet} treasury={treasury} />}

      {activeTab === "strategy" && (
        <section className="strategy-layout">
          <TreasuryPanel
            treasury={treasury}
            isBusy={isTreasuryBusy}
            onInitialize={handleInitializeTreasury}
            onRebalance={handleRebalanceTreasury}
            onApprovePact={handleApproveTreasuryPact}
            onSubmitAavePact={handleSubmitAavePact}
            onClaimAaveFaucet={handleClaimAaveFaucet}
            onSupplyAave={handleSupplyAave}
            onWithdrawAave={handleWithdrawAave}
          />
        </section>
      )}

      {activeTab === "history" && <HistoryPanel items={history} />}
    </main>
  );
}

export default App;
