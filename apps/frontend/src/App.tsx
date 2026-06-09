import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { HistoryItem, HistoryPanel } from "./components/HistoryPanel";
import { PortfolioPanel } from "./components/PortfolioPanel";
import { StrategyDataPanel } from "./components/StrategyDataPanel";
import { TreasuryPanel } from "./components/TreasuryPanel";
import {
  AuditLog,
  approveTreasuryPact,
  ChatResponse,
  executePendingTransfer,
  fetchPendingTransferStatus,
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
  withdrawAave,
} from "./api";

type StrategyPhase = "idle" | "submitting_pact" | "waiting_pact" | "executing" | "canceling" | "completed";

function App() {
  const [activeTab, setActiveTab] = useState<"chat" | "portfolio" | "strategy" | "strategyData" | "history">("chat");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [wallet, setWallet] = useState<WalletStatus | null>(null);
  const [treasury, setTreasury] = useState<TreasuryState | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [chatPendingText, setChatPendingText] = useState("正在处理请求...");
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
    setChatPendingText(getInitialChatPendingText(message));
    setError(null);
    setMessages([{ role: "user", content: message }]);
    const directTransferTimer = window.setTimeout(() => {
      if (looksLikeTransferRequest(message)) {
        setChatPendingText("正在检查余额和可用 Pact；如果已有授权，正在交易中...");
      }
    }, 1200);
    try {
      const response: ChatResponse = await sendChat(message);
      window.clearTimeout(directTransferTimer);
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
      await refreshTreasuryAfterChat();
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
      if (isWaitingForTransferApproval(response)) {
        setChatPendingText("已提交新的 CAW Pact，正在等待 owner approve...");
        const pendingResult = await waitForPendingTransferExecution((content) => {
          setChatPendingText(content);
          setMessages([
            { role: "user", content: message },
            {
              role: "agent",
              content,
              llmUsed: response.llm_used,
              cawUsed: true,
              memoryUpdated: response.memory_updated,
            },
          ]);
        });
        const pendingReply = buildPendingTransferReply(pendingResult);
        setMessages([
          { role: "user", content: message },
          {
            role: "agent",
            content: pendingReply,
            llmUsed: response.llm_used,
            cawUsed: true,
            memoryUpdated: response.memory_updated,
          },
        ]);
        const pendingTreasury = pendingResult.treasury as TreasuryState | undefined;
        if (pendingTreasury) {
          setTreasury(pendingTreasury);
        } else {
          await refreshTreasuryAfterChat();
        }
      } else if (response.caw_used && looksLikeTransferRequest(message)) {
        setIsSending(false);
      }
      await refreshStatusAfterChat();
    } catch (currentError) {
      window.clearTimeout(directTransferTimer);
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
      window.clearTimeout(directTransferTimer);
      setIsSending(false);
      setChatPendingText("正在处理请求...");
    }
  }

  async function refreshTreasuryAfterChat() {
    try {
      setTreasury(await fetchTreasuryState());
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Treasury refresh failed");
    }
  }

  async function refreshStatusAfterChat() {
    try {
      await refreshStatus();
    } catch {
      // Keep the successful chat result visible if a follow-up status refresh fails.
    }
  }

  async function handleExecuteStrategy() {
    setIsTreasuryBusy(true);
    setStrategyPhase("submitting_pact");
    setError(null);
    try {
      let currentTreasury = treasury ?? (await initializeTreasury("1000"));
      setTreasury(currentTreasury);

      currentTreasury = await ensureActiveInternalPact(
        currentTreasury,
        getStrategyPactAmount(currentTreasury),
        setTreasury,
        () => setStrategyPhase("waiting_pact"),
      );

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

  async function handleCancelStrategy() {
    setIsTreasuryBusy(true);
    setStrategyPhase("canceling");
    setError(null);
    try {
      let currentTreasury = treasury ?? (await fetchTreasuryState());
      const aaveBalance = getAaveBalance(currentTreasury);
      if (aaveBalance <= 0) {
        setTreasury(currentTreasury);
        setStrategyPhase("idle");
        return;
      }

      currentTreasury = await ensureActiveInternalPact(
        currentTreasury,
        formatPactAmount(aaveBalance),
        setTreasury,
        () => setStrategyPhase("waiting_pact"),
      );
      const activePact = findInternalPact(
        currentTreasury,
        (pact) => pact.status === "active" && Boolean(pact.caw_pact_id),
      );
      const pactId = activePact?.caw_pact_id ?? activePact?.pact_id;
      if (!pactId) {
        throw new Error("No active CAW Pact is available for Aave withdraw.");
      }

      const result = await withdrawAave(pactId, formatPactAmount(aaveBalance));
      assertAaveActionSucceeded(result, "Aave withdraw did not complete.");
      setTreasury((result.treasury as TreasuryState | undefined) ?? (await fetchTreasuryState()));
      setStrategyPhase("idle");
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Strategy cancellation failed");
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
          className={activeTab === "strategyData" ? "active" : ""}
          onClick={() => setActiveTab("strategyData")}
          type="button"
        >
          Strategy Data
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
          <ChatPanel messages={messages} isSending={isSending} pendingText={chatPendingText} onSend={handleSend} />
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
            onCancelStrategy={handleCancelStrategy}
            onApprovePact={handleApproveTreasuryPact}
          />
        </section>
      )}

      {activeTab === "strategyData" && <StrategyDataPanel profile={profile} treasury={treasury} />}

      {activeTab === "history" && <HistoryPanel items={history} />}
    </main>
  );
}

async function ensureActiveInternalPact(
  treasury: TreasuryState,
  maxAmount: string,
  onState: (treasuryState: TreasuryState) => void,
  onWaitingForApproval: () => void,
): Promise<TreasuryState> {
  const activePact = findInternalPact(treasury, (pact) => pact.status === "active" && Boolean(pact.caw_pact_id));
  if (activePact) {
    return treasury;
  }

  const pendingPact = (await submitAavePact(maxAmount)) as LocalPact;
  if (!pendingPact.pact_id || !pendingPact.caw_pact_id) {
    const reason = pendingPact.reason || "CAW did not return a Pact ID for approval.";
    throw new Error(reason);
  }
  const currentTreasury = await fetchTreasuryState();
  onState(currentTreasury);
  onWaitingForApproval();
  return waitForPactActive(pendingPact.pact_id, onState);
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

function getAaveBalance(treasury: TreasuryState) {
  const value = treasury.balances.yield ?? treasury.balances.aave ?? treasury.aave?.aave_balance ?? "0";
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : 0;
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

function assertAaveActionSucceeded(result: Record<string, unknown>, fallbackReason: string) {
  const status = String(result.status ?? "");
  if (["error", "pact_not_active", "approve_failed", "execution_failed", "missing_wallet_address"].includes(status)) {
    const reason = String(result.reason ?? fallbackReason);
    throw new Error(reason);
  }
}

function getInitialChatPendingText(message: string) {
  if (looksLikeTransferRequest(message)) {
    return "正在检查余额和可用 Pact...";
  }
  return "正在处理请求...";
}

function looksLikeTransferRequest(message: string) {
  const normalized = message.toLowerCase();
  return (
    /0x[a-f0-9]{40}/i.test(message) &&
    (normalized.includes("transfer") ||
      normalized.includes("send") ||
      normalized.includes("转账") ||
      normalized.includes("发送") ||
      normalized.includes("给"))
  );
}

function isWaitingForTransferApproval(response: ChatResponse) {
  const proposal = response.proposal as Record<string, unknown> | null;
  const pendingExecution = proposal?.pending_execution as { status?: string } | undefined;
  return proposal?.pact_type === "external_transfer" && pendingExecution?.status === "pending_owner_approval";
}

async function waitForPendingTransferExecution(onProgress: (content: string) => void): Promise<Record<string, unknown>> {
  let executionAnnounced = false;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const pendingStatus = await fetchPendingTransferStatus();
    const status = String(pendingStatus.status ?? "");
    if (status === "ready_to_execute") {
      if (!executionAnnounced) {
        executionAnnounced = true;
        onProgress("Pact 已通过，正在交易中...");
      }
      const result = await executePendingTransfer();
      const executionStatus = String(result.status ?? "");
      if (["completed", "execution_failed", "blocked_legacy_pact"].includes(executionStatus)) {
        return result;
      }
    } else if (["approval_stopped", "blocked_legacy_pact", "execution_failed"].includes(status)) {
      return pendingStatus;
    } else if (status === "no_pending_transfer") {
      return { status, reason: "没有找到等待中的转账 Pact。请重新发起转账请求。" };
    }
    await delay(3000);
  }
  return { status: "pending_owner_approval", reason: "Pact is active check is still pending. Please try Refresh Status." };
}

function buildPendingTransferReply(result: Record<string, unknown>) {
  const status = String(result.status ?? "");
  if (status === "completed") {
    const execution = result.execution as Record<string, unknown> | undefined;
    const gasFee = extractGasFeeText(result, execution);
    return `Pact 已生效，Agent 已继续执行转账。Gas fee：${String(gasFee)}。`;
  }
  const reason = String(result.reason ?? "转账尚未完成。");
  return reason;
}

function extractGasFeeText(result: Record<string, unknown>, execution?: Record<string, unknown>) {
  const transfer = execution?.transfer as Record<string, unknown> | undefined;
  const transaction = execution?.transaction as Record<string, unknown> | undefined;
  const transactionFee = firstTransactionFee(transaction);
  const candidates = [
    result.gas_fee,
    result.fee,
    result.gas_cost,
    execution?.gas_fee,
    execution?.fee,
    execution?.gas_cost,
    transfer?.gas_fee,
    transfer?.fee,
    transfer?.gas_cost,
    transfer?.transaction_fee,
    transfer?.fee_amount,
    transactionFee?.fee_used,
    transactionFee?.estimated_fee_used,
  ];
  for (const candidate of candidates) {
    if (candidate !== undefined && candidate !== null && String(candidate) !== "") {
      const tokenId = transactionFee?.token_id;
      if ((candidate === transactionFee?.fee_used || candidate === transactionFee?.estimated_fee_used) && tokenId) {
        return `${String(candidate)} ${String(tokenId)}`;
      }
      return String(candidate);
    }
  }
  const transferStatus = transfer?.status_display ?? transfer?.status;
  if (transferStatus) {
    return `CAW 返回结果中未提供（交易状态：${String(transferStatus)}）`;
  }
  const transactionStatus = transaction?.status;
  if (transactionStatus) {
    return `CAW 交易详情暂未返回 fee（交易状态：${String(transactionStatus)}）`;
  }
  return "CAW 返回结果中未提供";
}

function firstTransactionFee(transaction?: Record<string, unknown>) {
  const topLevelFee = transaction?.fee as Record<string, unknown> | undefined;
  if (topLevelFee) {
    return topLevelFee;
  }
  const data = transaction?.data as Record<string, unknown> | undefined;
  const dataFee = data?.fee as Record<string, unknown> | undefined;
  if (dataFee) {
    return dataFee;
  }
  const preparedTx = transaction?.prepared_tx as Record<string, unknown> | undefined;
  const preparedFee = preparedTx?.fee as Record<string, unknown> | undefined;
  if (preparedFee) {
    return preparedFee;
  }
  const extTransactions = transaction?.ext_transactions as Array<Record<string, unknown>> | undefined;
  for (const extTransaction of extTransactions ?? []) {
    const extData = extTransaction.data as Record<string, unknown> | undefined;
    const extFee = extData?.fee as Record<string, unknown> | undefined;
    if (extFee) {
      return extFee;
    }
  }
  return undefined;
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default App;
