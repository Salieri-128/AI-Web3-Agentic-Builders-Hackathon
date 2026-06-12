import { useEffect, useState } from "react";
import { ChatPanel, ChatTurn } from "./components/ChatPanel";
import { ClassificationAttentionBanner } from "./components/ClassificationAttentionBanner";
import { FundsOptimizationPanel } from "./components/FundsOptimizationPanel";
import { HistoryItem, HistoryPanel } from "./components/HistoryPanel";
import { PortfolioPanel } from "./components/PortfolioPanel";
import {
  applyTransferClassification,
  AuditLog,
  approveTreasuryPact,
  ChatResponse,
  Clarification,
  confirmMemoryProposal,
  confirmTransferClassification,
  executePendingTransfer,
  fetchPendingTransferStatus,
  fetchProfile,
  fetchStatus,
  fetchTreasuryState,
  fetchWalletStatus,
  initializeTreasury,
  LocalPact,
  MemoryProposal,
  Profile,
  Proposal,
  previewTreasuryRebalance,
  rebalanceTreasury,
  rejectMemoryProposal,
  rejectTransferClassification,
  selectTreasuryPlan,
  sendChat,
  StatusResponse,
  submitAavePact,
  syncTreasury,
  syncWorkspace,
  TreasuryState,
  TreasuryPlan,
  TransferClassificationProposal,
  WalletStatus,
  withdrawAave,
} from "./api";

type StrategyPhase =
  | "idle"
  | "submitting_pact"
  | "waiting_pact"
  | "executing"
  | "cancel_submitting_pact"
  | "cancel_waiting_pact"
  | "canceling"
  | "completed";

type AppTab = "chat" | "portfolio" | "optimization" | "history";

const TAB_META: Array<{
  id: AppTab;
  index: string;
  label: string;
  title: string;
  description: string;
}> = [
  {
    id: "chat",
    index: "01",
    label: "Wallet",
    title: "Simple wallet",
    description: "Check balances, receive funds, and send protected transfers without managing treasury parameters.",
  },
  {
    id: "portfolio",
    index: "02",
    label: "Portfolio",
    title: "Asset overview",
    description: "Inspect wallet and Aave positions across the demo environment without exposing execution credentials.",
  },
  {
    id: "optimization",
    index: "03",
    label: "Funds optimization",
    title: "Funds optimization",
    description: "Activate the Aave strategy first, then optionally tune yield and liquidity goals with the AI planner.",
  },
  {
    id: "history",
    index: "04",
    label: "Audit trail",
    title: "Execution history",
    description: "Review prior requests and the full structured result returned by the agent.",
  },
];

function App() {
  const [activeTab, setActiveTab] = useState<AppTab>("chat");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [wallet, setWallet] = useState<WalletStatus | null>(null);
  const [treasury, setTreasury] = useState<TreasuryState | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [optimizationMessages, setOptimizationMessages] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [chatPendingText, setChatPendingText] = useState("正在处理请求...");
  const [isTreasuryBusy, setIsTreasuryBusy] = useState(false);
  const [strategyPhase, setStrategyPhase] = useState<StrategyPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [incomingNotice, setIncomingNotice] = useState<string | null>(null);
  const [memoryProposal, setMemoryProposal] = useState<MemoryProposal | null>(null);
  const [isMemoryBusy, setIsMemoryBusy] = useState(false);
  const [planningSessionId, setPlanningSessionId] = useState<string | null>(null);
  const [clarification, setClarification] = useState<Clarification | null>(null);
  const [treasuryPlan, setTreasuryPlan] = useState<TreasuryPlan | null>(null);
  const [transferClassificationProposal, setTransferClassificationProposal] =
    useState<TransferClassificationProposal | null>(null);
  const [isPlannerBusy, setIsPlannerBusy] = useState(false);
  const [isClassificationBusy, setIsClassificationBusy] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);

  useEffect(() => {
    refreshStatus();
  }, []);

  useEffect(() => {
    if (activeTab === "optimization") {
      void refreshRebalancePreview();
    }
  }, [activeTab]);

  useEffect(() => {
    const syncIfVisible = () => {
      if (document.visibilityState === "visible") {
        void syncIncomingFunds();
      }
    };
    const intervalId = window.setInterval(syncIfVisible, 15000);
    document.addEventListener("visibilitychange", syncIfVisible);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", syncIfVisible);
    };
  }, []);

  async function refreshStatus() {
    try {
      const [nextStatus, nextProfile, nextWallet, nextTreasury] = await Promise.all([
        fetchStatus(),
        fetchProfile(),
        fetchWalletStatus(),
        fetchTreasuryState(),
      ]);
      setStatus(nextStatus);
      setProfile(nextProfile);
      setWallet(nextWallet);
      setTreasury(nextTreasury);
      setError(null);
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Backend status failed");
    }
  }

  async function handleSend(message: string) {
    const strategyActive = isTreasuryStrategyActive(treasury, strategyPhase);
    const isOptimizationRequest =
      activeTab === "optimization" ||
      Boolean(planningSessionId) ||
      looksLikeTreasuryGoal(message);
    if (isOptimizationRequest && !strategyActive) {
      const unlockReply = "请先在资金优化页执行安心生息策略。策略运行后，才会解锁资金目标和 AI Planner。";
      setMessages((current) => [
        ...current,
        { role: "user", content: message },
        { role: "agent", content: unlockReply },
      ]);
      setActiveTab("optimization");
      return;
    }

    setIsSending(true);
    setChatPendingText(getInitialChatPendingText(message));
    setError(null);
    const userTurn: ChatTurn = { role: "user", content: message };
    setMessages((current) => [...current, userTurn]);
    if (isOptimizationRequest) {
      setOptimizationMessages([userTurn]);
    }
    const directTransferTimer = window.setTimeout(() => {
      if (looksLikeTransferRequest(message)) {
        setChatPendingText("正在检查余额和可用 Pact；如果已有授权，正在交易中...");
      }
    }, 1200);
    try {
      const response: ChatResponse = await sendChat(message, planningSessionId);
      window.clearTimeout(directTransferTimer);
      const responseTurn: ChatTurn = {
        role: "agent",
        content: response.reply,
        llmUsed: response.llm_used,
        cawUsed: response.caw_used,
        memoryUpdated: response.memory_updated,
      };
      setMessages((current) => [...current, responseTurn]);
      if (isOptimizationRequest) {
        setOptimizationMessages([userTurn, responseTurn]);
      }
      setProposal(response.proposal);
      setMemoryProposal(response.memory_proposal ?? null);
      setPlanningSessionId(response.planning_session_id ?? null);
      setClarification(response.clarification ?? null);
      setTreasuryPlan(response.treasury_plan ?? null);
      setTransferClassificationProposal(
        response.transfer_classification_proposal ?? null,
      );
      if (
        response.memory_proposal ||
        response.clarification ||
        response.treasury_plan ||
        response.transfer_classification_proposal
      ) {
        setActiveTab("optimization");
      }
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
        const pendingResult = await waitForPendingTransferExecution(setChatPendingText);
        const pendingReply = buildPendingTransferReply(pendingResult);
        setMessages((current) => [
          ...current,
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
      setMessages((current) => [
        ...current,
        { role: "agent", content: messageText },
      ]);
      if (isOptimizationRequest) {
        setOptimizationMessages([
          userTurn,
          { role: "agent", content: messageText },
        ]);
      }
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

  function publishOptimizationResult(turn: ChatTurn) {
    setMessages((current) => [...current, turn]);
    setOptimizationMessages((current) => {
      const userTurn = [...current].reverse().find((message) => message.role === "user");
      return userTurn ? [userTurn, turn] : [turn];
    });
  }

  async function refreshStatusAfterChat() {
    try {
      await refreshStatus();
    } catch {
      // Keep the successful chat result visible if a follow-up status refresh fails.
    }
  }

  async function refreshRebalancePreview() {
    try {
      const preview = await previewTreasuryRebalance();
      setTreasury((current) =>
        current
          ? { ...current, liquidity: preview.liquidity, rebalance_preview: preview }
          : current,
      );
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Rebalance preview failed");
    }
  }

  async function syncIncomingFunds() {
    try {
      const result = await syncTreasury();
      const syncedTreasury = result.treasury as TreasuryState | undefined;
      if (syncedTreasury) {
        setTreasury(syncedTreasury);
      }
      const incomingAmount = Number(result.incoming_amount ?? 0);
      if (String(result.status) === "incoming_funds_detected" && incomingAmount > 0) {
        setIncomingNotice(`收到 ${String(result.incoming_amount)} WBTC，已更新 Rebalance 建议，不会自动存入 Aave。`);
        await refreshRebalancePreview();
      }
    } catch {
      // Background balance sync should not interrupt the active user flow.
    }
  }

  async function handleSyncWorkspace() {
    setIsSyncing(true);
    setError(null);
    const previousLiquidity = treasury?.recommendation.recommended_liquidity;
    const previousPacts = treasury?.pacts.map((pact) => `${pact.pact_id}:${pact.status}`).join("|");
    try {
      const result = await syncWorkspace();
      setStatus(result.system_status);
      setProfile(result.profile);
      setTreasury(result.treasury);
      if (result.treasury.wallet_status) {
        setWallet(result.treasury.wallet_status);
      }
      setLastSyncedAt(result.synced_at);

      const nextLiquidity = result.treasury.recommendation.recommended_liquidity;
      const nextPacts = result.treasury.pacts.map((pact) => `${pact.pact_id}:${pact.status}`).join("|");
      const changes: string[] = [];
      if (previousLiquidity && previousLiquidity !== nextLiquidity) {
        changes.push(`建议保留从 ${previousLiquidity} 调整为 ${nextLiquidity} ${result.treasury.asset}`);
      }
      if (previousPacts !== undefined && previousPacts !== nextPacts) {
        changes.push("Pact 状态已更新");
      }
      if (Number(result.incoming_amount) > 0) {
        changes.push(`检测到 ${result.incoming_amount} ${result.treasury.asset} 新入账`);
      }
      setSyncNotice(changes.length ? changes.join("；") : "余额、Pact、画像和策略建议均已同步，没有发现变化。");
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Workspace sync failed");
    } finally {
      setIsSyncing(false);
    }
  }

  async function handleConfirmMemory(proposalId: string) {
    setIsMemoryBusy(true);
    setError(null);
    try {
      const result = await confirmMemoryProposal(proposalId);
      const impact = memoryProposal?.liquidity_impact;
      setProfile(result.profile);
      setTreasury(result.treasury);
      setMemoryProposal(null);
      publishOptimizationResult({
        role: "agent",
        content: impact
          ? `画像已应用。建议保留流动性从 ${impact.before.recommended_liquidity} 调整为 ${impact.after.recommended_liquidity} ${impact.asset}。CAW Pact 权限未改变。`
          : "画像已应用，流动性建议已重新计算。",
        memoryUpdated: true,
      });
      setSyncNotice("用户画像已应用，流动性建议已重新计算。");
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Memory proposal failed");
    } finally {
      setIsMemoryBusy(false);
    }
  }

  async function handleRejectMemory(proposalId: string) {
    setIsMemoryBusy(true);
    setError(null);
    try {
      const result = await rejectMemoryProposal(proposalId);
      setProfile(result.profile);
      setMemoryProposal(null);
      publishOptimizationResult({
        role: "agent",
        content: "画像变更已拒绝，当前流动性策略保持不变。",
      });
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Memory proposal rejection failed");
    } finally {
      setIsMemoryBusy(false);
    }
  }

  async function handleSelectTreasuryPlan(planId: string, scenarioId: string) {
    setIsPlannerBusy(true);
    setError(null);
    const selectedScenario = treasuryPlan?.scenarios.find(
      (scenario) => scenario.scenario_id === scenarioId,
    );
    try {
      const result = await selectTreasuryPlan(planId, scenarioId);
      setProfile(result.profile);
      setTreasury(result.treasury);
      setTreasuryPlan(null);
      setClarification(null);
      setPlanningSessionId(null);
      publishOptimizationResult({
        role: "agent",
        content: selectedScenario
          ? `已应用${selectedScenario.label}：建议保留 ${selectedScenario.after.recommended_liquidity} WBTC，Aave 目标 ${selectedScenario.after.target_yield_balance} WBTC。这里只更新策略输入，没有提交 Pact 或执行资金操作。`
          : "方案已应用，策略建议已重新计算；CAW Pact 和执行状态未改变。",
        memoryUpdated: true,
      });
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Treasury plan selection failed");
    } finally {
      setIsPlannerBusy(false);
    }
  }

  async function handleConfirmTransferClassification(proposalId: string) {
    setIsPlannerBusy(true);
    setError(null);
    const currentProposal = transferClassificationProposal;
    try {
      const result = await confirmTransferClassification(proposalId);
      setProfile(result.profile);
      setTreasury(result.treasury);
      setTransferClassificationProposal(null);
      setClarification(null);
      setPlanningSessionId(null);
      publishOptimizationResult({
        role: "agent",
        content: currentProposal
          ? `历史分类已应用。经常性总额从 ${currentProposal.statistics_before.recurring_transfer_sum} 调整为 ${currentProposal.statistics_after.recurring_transfer_sum} WBTC，原始审计事件保持不变。`
          : "历史分类已应用，流动性建议已重新计算。",
        memoryUpdated: true,
      });
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Transfer classification failed");
    } finally {
      setIsPlannerBusy(false);
    }
  }

  async function handleRejectTransferClassification(proposalId: string) {
    setIsPlannerBusy(true);
    setError(null);
    try {
      await rejectTransferClassification(proposalId);
      setTransferClassificationProposal(null);
      setPlanningSessionId(null);
      publishOptimizationResult({
        role: "agent",
        content: "已保持自动分类结果，流动性模型和原始审计记录都没有变化。",
      });
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Classification rejection failed");
    } finally {
      setIsPlannerBusy(false);
    }
  }

  async function handleClassificationAttention(
    eventId: string,
    classification: "one_off" | "recurring",
  ) {
    setIsClassificationBusy(true);
    setError(null);
    try {
      const result = await applyTransferClassification(eventId, classification);
      setProfile(result.profile);
      setTreasury(result.treasury);
      setSyncNotice(
        classification === "one_off"
          ? "已确认该笔转账为一次性，后台流动性建议已更新。"
          : "已将该笔转账视为经常性，后台流动性建议已更新。",
      );
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "Classification update failed");
    } finally {
      setIsClassificationBusy(false);
    }
  }

  async function handleExecuteStrategy() {
    setIsTreasuryBusy(true);
    setStrategyPhase("submitting_pact");
    setError(null);
    try {
      let currentTreasury = treasury ?? (await initializeTreasury("1000"));
      const preview = await previewTreasuryRebalance();
      currentTreasury = {
        ...currentTreasury,
        liquidity: preview.liquidity,
        rebalance_preview: preview,
      };
      setTreasury(currentTreasury);
      if (!preview.allowed && preview.action === "hold") {
        setStrategyPhase("idle");
        return;
      }

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
    setStrategyPhase("cancel_submitting_pact");
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
        () => setStrategyPhase("cancel_waiting_pact"),
      );
      setStrategyPhase("canceling");
      const activePact = findInternalPact(
        currentTreasury,
        (pact) => isActivePactForAmount(pact, aaveBalance),
      );
      const pactId = activePact?.caw_pact_id ?? activePact?.pact_id;
      if (!pactId) {
        throw new Error("No active CAW Pact with sufficient allowance is available for Aave withdraw.");
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

  const activeTabMeta = TAB_META.find((tab) => tab.id === activeTab) ?? TAB_META[0];
  const servicesOnline = status?.backend === "ok" || status?.backend === "ready";
  const strategyActive = isTreasuryStrategyActive(treasury, strategyPhase);

  return (
    <main className={`app-shell ${activeTab === "chat" ? "wallet-shell" : ""}`}>
      <a className="skip-link" href="#workspace-content">Skip to workspace</a>

      <aside className="app-sidebar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <strong>CAW / TREASURY</strong>
            <small>Agentic control plane</small>
          </div>
        </div>

        <nav className="tab-bar" aria-label="Primary navigation">
          {TAB_META.map((tab) => (
            <button
              aria-current={activeTab === tab.id ? "page" : undefined}
              className={activeTab === tab.id ? "active" : ""}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              type="button"
            >
              <span>{tab.index}</span>
              <strong>{tab.label}</strong>
            </button>
          ))}
        </nav>

        <div className="sidebar-boundary">
          <span className="boundary-label">Permission boundary</span>
          <strong>Pact enforced</strong>
          <p>Agent proposes. Owner approves. CAW executes.</p>
        </div>

        <div className="sidebar-foot">
          <span className={`status-dot ${servicesOnline ? "online" : ""}`} aria-hidden="true" />
          <div>
            <strong>{servicesOnline ? "Systems nominal" : "Checking systems"}</strong>
            <small>{treasury?.mode?.includes("sepolia_real") ? "Sepolia environment" : "Local demo environment"}</small>
          </div>
        </div>
      </aside>

      <section className={`app-workspace ${activeTab === "chat" ? "wallet-workspace" : ""}`}>
        <header className="app-header">
          <div className="page-heading">
            <span className="page-index">Workspace / {activeTabMeta.index}</span>
            <h1>{activeTabMeta.title}</h1>
            <p>{activeTabMeta.description}</p>
          </div>
          <div className="header-actions">
            <div className="system-pills" aria-label="System configuration">
              <span className={status?.caw_configured ? "ready" : ""}>CAW</span>
              <span className={status?.llm_configured ? "ready" : ""}>LLM</span>
              <span className={status?.memory_loaded ? "ready" : ""}>MEM</span>
            </div>
            <button
              className={`secondary-button refresh-button ${isSyncing ? "syncing" : ""}`}
              disabled={isSyncing}
              onClick={handleSyncWorkspace}
              type="button"
            >
              <span aria-hidden="true">↻</span>
              {isSyncing ? "Syncing..." : "Sync now"}
            </button>
            {lastSyncedAt && (
              <small className="last-synced">Synced {formatSyncTime(lastSyncedAt)}</small>
            )}
          </div>
        </header>

        <section
          className={`workspace-content ${activeTab === "chat" ? "wallet-content" : ""}`}
          id="workspace-content"
        >
          {error && <div className="error-banner" role="alert">{error}</div>}
          {incomingNotice && (
            <div className="incoming-banner" role="status">
              <span>{incomingNotice}</span>
              <button onClick={() => setIncomingNotice(null)} type="button">关闭</button>
            </div>
          )}
          {syncNotice && (
            <div className="sync-banner" role="status">
              <span>{syncNotice}</span>
              <button onClick={() => setSyncNotice(null)} type="button">关闭</button>
            </div>
          )}
          {treasury?.classification_attention && (
            <ClassificationAttentionBanner
              attention={treasury.classification_attention}
              isBusy={isClassificationBusy}
              onClassify={handleClassificationAttention}
            />
          )}

          {activeTab === "chat" && (
            <section className="chat-tab-layout">
              <ChatPanel
                messages={messages}
                isSending={isSending}
                pendingText={chatPendingText}
                onSend={handleSend}
                walletAddress={getWalletAddress(wallet, treasury)}
                asset={treasury?.asset ?? "WBTC"}
                onOpenOptimization={() => setActiveTab("optimization")}
              />
            </section>
          )}

          {activeTab === "portfolio" && <PortfolioPanel wallet={wallet} treasury={treasury} />}

          {activeTab === "optimization" && (
            <FundsOptimizationPanel
              messages={optimizationMessages}
              strategyActive={strategyActive}
              isSending={isSending}
              onSend={handleSend}
              profile={profile}
              treasury={treasury}
              memoryProposal={memoryProposal}
              clarification={clarification}
              treasuryPlan={treasuryPlan}
              transferClassificationProposal={transferClassificationProposal}
              isMemoryBusy={isMemoryBusy || isSending}
              isPlannerBusy={isPlannerBusy || isSending}
              isTreasuryBusy={isTreasuryBusy}
              strategyPhase={strategyPhase}
              onConfirmMemory={handleConfirmMemory}
              onRejectMemory={handleRejectMemory}
              onSelectTreasuryPlan={handleSelectTreasuryPlan}
              onConfirmTransferClassification={handleConfirmTransferClassification}
              onRejectTransferClassification={handleRejectTransferClassification}
              onExecuteStrategy={handleExecuteStrategy}
              onCancelStrategy={handleCancelStrategy}
              onApprovePact={handleApproveTreasuryPact}
            />
          )}

          {activeTab === "history" && <HistoryPanel items={history} />}
        </section>
      </section>
    </main>
  );
}

async function ensureActiveInternalPact(
  treasury: TreasuryState,
  maxAmount: string,
  onState: (treasuryState: TreasuryState) => void,
  onWaitingForApproval: () => void,
): Promise<TreasuryState> {
  const requiredAmount = Number(maxAmount);
  let currentTreasury = treasury;
  const activePact = findInternalPact(currentTreasury, (pact) =>
    isActivePactForAmount(pact, requiredAmount),
  );
  if (activePact) {
    await approveTreasuryPact(activePact.pact_id);
    currentTreasury = await fetchTreasuryState();
    onState(currentTreasury);
    if (
      findInternalPact(currentTreasury, (pact) =>
        isActivePactForAmount(pact, requiredAmount),
      )
    ) {
      return currentTreasury;
    }
  }

  const existingPendingPact = findInternalPact(
    currentTreasury,
    (pact) =>
      isPendingPact(pact) &&
      Boolean(pact.caw_pact_id) &&
      getPactMaxAmount(pact) >= requiredAmount,
  );
  if (existingPendingPact) {
    onWaitingForApproval();
    return waitForPactActive(existingPendingPact.pact_id, onState);
  }

  const pendingPact = (await submitAavePact(maxAmount)) as LocalPact;
  if (!pendingPact.pact_id || !pendingPact.caw_pact_id) {
    const reason = pendingPact.reason || "CAW did not return a Pact ID for approval.";
    throw new Error(reason);
  }
  currentTreasury = await fetchTreasuryState();
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

function isActivePactForAmount(pact: LocalPact, requiredAmount: number) {
  return (
    pact.status === "active" &&
    Boolean(pact.caw_pact_id) &&
    getPactMaxAmount(pact) >= requiredAmount
  );
}

function isPendingPact(pact: LocalPact) {
  return ["pending", "pending_approval", "pending_owner_approval"].includes(pact.status);
}

function getPactMaxAmount(pact: LocalPact) {
  const maxAmount = Number(pact.scope.max_amount ?? 0);
  return Number.isFinite(maxAmount) ? maxAmount : 0;
}

function getStrategyPactAmount(treasury: TreasuryState) {
  const wallet = Number(treasury.balances.wallet_available ?? treasury.balances.wallet);
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

function getWalletAddress(
  wallet: WalletStatus | null,
  treasury: TreasuryState | null,
) {
  if (treasury?.aave?.wallet_address) {
    return treasury.aave.wallet_address;
  }
  const sepoliaAddress = wallet?.addresses?.find(
    (item) => String(item.chain_id ?? "") === "SETH",
  );
  const fallbackAddress = sepoliaAddress ?? wallet?.addresses?.[0];
  return fallbackAddress ? String(fallbackAddress.address ?? "") : null;
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
  if (
    [
      "error",
      "pact_not_active",
      "approve_failed",
      "withdraw_failed",
      "execution_failed",
      "missing_wallet_address",
    ].includes(status)
  ) {
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

function isTreasuryStrategyActive(
  treasury: TreasuryState | null,
  strategyPhase: StrategyPhase,
) {
  if (
    [
      "cancel_submitting_pact",
      "cancel_waiting_pact",
      "canceling",
    ].includes(strategyPhase)
  ) {
    return false;
  }
  const aaveBalance = Number(
    treasury?.balances.yield ?? treasury?.balances.aave ?? 0,
  );
  return strategyPhase === "completed" || aaveBalance > 0;
}

function looksLikeTreasuryGoal(message: string) {
  const normalized = message.toLowerCase();
  return [
    "提高收益",
    "资金优化",
    "至少保留",
    "覆盖",
    "下周",
    "未来支出",
    "低 gas",
    "低gas",
    "保守",
    "激进",
    "流动性",
    "optimize",
    "yield",
    "liquidity",
    "conservative",
    "aggressive",
  ].some((keyword) => normalized.includes(keyword));
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
  const responseWallet = response.wallet as (WalletStatus & { treasury?: TreasuryState }) | null;
  const pendingStage = responseWallet?.treasury?.pending_transfer?.stage;
  return (
    (proposal?.pact_type === "external_transfer" && pendingExecution?.status === "waiting_transfer_pact") ||
    pendingExecution?.status === "pending_owner_approval" ||
    ["waiting_transfer_pact", "waiting_aave_pact", "checking_balance", "estimating_gas"].includes(pendingStage ?? "")
  );
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
      if (executionStatus === "pact_required" || executionStatus === "pending_owner_approval") {
        onProgress("当前没有额度足够的目标地址转账 Pact，已提交新 Pact，请在 Cobo App 中审批...");
      } else if (executionStatus === "waiting_aave_pact") {
        const pending = result.pending_transfer as { withdraw_amount?: string } | undefined;
        onProgress(
          `已计算需从 Aave 取回 ${pending?.withdraw_amount ?? "足够的"} WBTC，正在等待 Aave Pact 审批...`,
        );
      }
      if (
        [
          "completed",
          "execution_failed",
          "blocked_legacy_pact",
          "fee_estimation_failed",
          "insufficient_gas_balance",
          "withdraw_failed",
          "transfer_failed",
        ].includes(executionStatus)
      ) {
        return result;
      }
    } else if (status === "waiting_aave_pact") {
      onProgress("转账 Pact 已通过，正在等待 Aave 取款 Pact 审批...");
    } else if (
      [
        "approval_stopped",
        "blocked_legacy_pact",
        "execution_failed",
        "fee_estimation_failed",
        "insufficient_gas_balance",
        "withdraw_failed",
        "transfer_failed",
      ].includes(status)
    ) {
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

function formatSyncTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "just now";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export default App;
