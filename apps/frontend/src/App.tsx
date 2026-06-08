import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { HistoryItem, HistoryPanel } from "./components/HistoryPanel";
import { PortfolioPanel } from "./components/PortfolioPanel";
import { TreasuryPanel } from "./components/TreasuryPanel";
import {
  AuditLog,
  approveTreasuryPact,
  ChatResponse,
  fetchProfile,
  fetchStatus,
  fetchTreasuryState,
  fetchWalletStatus,
  initializeTreasury,
  LocalPact,
  Profile,
  Proposal,
  rebalanceTreasury,
  sendChat,
  StatusResponse,
  submitAavePact,
  TreasuryState,
  WalletStatus,
} from "./api";

type StrategyPhase = "idle" | "submitting_pact" | "waiting_pact" | "executing" | "completed";

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
  const [strategyPhase, setStrategyPhase] = useState<StrategyPhase>("idle");
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

  async function handleExecuteStrategy() {
    setIsTreasuryBusy(true);
    setStrategyPhase("submitting_pact");
    setError(null);
    try {
      let currentTreasury = treasury ?? (await initializeTreasury("1000"));
      setTreasury(currentTreasury);

      const activePact = findInternalPact(
        currentTreasury,
        (pact) => pact.status === "active" && Boolean(pact.caw_pact_id),
      );
      if (!activePact) {
        const maxAmount = getStrategyPactAmount(currentTreasury);
        const pendingPact = (await submitAavePact(maxAmount)) as LocalPact;
        if (!pendingPact.pact_id || !pendingPact.caw_pact_id) {
          const reason = pendingPact.reason || "CAW did not return a Pact ID for approval.";
          throw new Error(reason);
        }
        currentTreasury = await fetchTreasuryState();
        setTreasury(currentTreasury);
        setStrategyPhase("waiting_pact");
        currentTreasury = await waitForPactActive(pendingPact.pact_id, setTreasury);
      }

      setStrategyPhase("executing");
      const result = await rebalanceTreasury();
      assertRebalanceSucceeded(result);
      setTreasury((result.treasury as TreasuryState | undefined) ?? (await fetchTreasuryState()));
      setStrategyPhase("completed");
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Strategy execution failed");
      try {
        setTreasury(await fetchTreasuryState());
      } catch {
        // Keep the visible error from the strategy action when status refresh also fails.
      }
      setStrategyPhase("idle");
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
            strategyPhase={strategyPhase}
            onExecuteStrategy={handleExecuteStrategy}
            onApprovePact={handleApproveTreasuryPact}
          />
        </section>
      )}

      {activeTab === "history" && <HistoryPanel items={history} />}
    </main>
  );
}

async function waitForPactActive(pactId: string, onState: (treasuryState: TreasuryState) => void): Promise<TreasuryState> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const result = await approveTreasuryPact(pactId);
    const treasuryState = await fetchTreasuryState();
    onState(treasuryState);
    const pact = findInternalPact(treasuryState, (item) => item.pact_id === pactId || item.caw_pact_id === pactId);
    const status = String(result.status ?? pact?.status ?? "");
    if (status === "active" || pact?.status === "active") {
      return treasuryState;
    }
    if (["revoked", "rejected", "declined", "caw_submission_failed", "error"].includes(status)) {
      throw new Error(`CAW Pact is ${status}. Please submit a new strategy authorization.`);
    }
    await delay(3000);
  }
  throw new Error("CAW Pact is still waiting for approval. Please approve it in the Cobo App and try again.");
}

function findInternalPact(treasury: TreasuryState, predicate: (pact: LocalPact) => boolean) {
  return treasury.pacts.find((pact) => pact.pact_type === "internal_agent_rebalance" && predicate(pact));
}

function getStrategyPactAmount(treasury: TreasuryState) {
  const wallet = Number(treasury.balances.wallet);
  const total = Number(treasury.balances.total);
  const amount = Math.max(wallet, total, 1);
  return Number.isFinite(amount) ? formatPactAmount(amount) : "1";
}

function formatPactAmount(amount: number) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 8,
    minimumFractionDigits: 0,
    useGrouping: false,
  }).format(amount);
}

function assertRebalanceSucceeded(result: Record<string, unknown>) {
  const status = String(result.status ?? "");
  if (status === "execution_failed" || status === "internal_rebalance_pact_required") {
    const decision = result.decision as { reason?: string; execution?: { reason?: string; status?: string } } | undefined;
    const reason = decision?.execution?.reason ?? decision?.reason ?? "Aave strategy execution did not complete.";
    throw new Error(reason);
  }
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default App;
