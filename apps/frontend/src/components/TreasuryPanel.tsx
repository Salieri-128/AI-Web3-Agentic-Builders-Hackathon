import { TreasuryState } from "../api";

type StrategyPhase =
  | "idle"
  | "submitting_pact"
  | "waiting_pact"
  | "executing"
  | "cancel_submitting_pact"
  | "cancel_waiting_pact"
  | "canceling"
  | "completed";

type TreasuryPanelProps = {
  treasury: TreasuryState | null;
  isBusy: boolean;
  strategyPhase: StrategyPhase;
  onExecuteStrategy: () => void;
  onCancelStrategy: () => void;
  onApprovePact: (pactId: string) => void;
};

export function TreasuryPanel({
  treasury,
  isBusy,
  strategyPhase,
  onExecuteStrategy,
  onCancelStrategy,
  onApprovePact,
}: TreasuryPanelProps) {
  const internalPact = getDisplayInternalPact(treasury);
  const walletBalance = treasury?.balances.wallet ?? "0";
  const yieldBalance = treasury?.balances.yield ?? treasury?.balances.aave ?? "0";
  const totalBalance = treasury?.balances.total ?? "0";
  const strategyAsset = treasury?.asset ?? treasury?.aave?.asset ?? "WBTC";
  const availableAmount = Number(walletBalance);
  const totalAmount = Number(totalBalance);
  const liquidityRatio = totalAmount > 0 ? Math.min(100, Math.max(0, (availableAmount / totalAmount) * 100)) : 0;
  const liquidityLabel = `${liquidityRatio.toFixed(0)}%`;
  const hasAavePosition = Number(yieldBalance) > 0;
  const isStrategyActive = strategyPhase === "completed" || hasAavePosition;
  const pactStatus = getPactStatusLabel(internalPact?.status);
  const pactNeedsRefresh = internalPact?.status === "pending_owner_approval";
  const isCancelPhase = [
    "cancel_submitting_pact",
    "cancel_waiting_pact",
    "canceling",
  ].includes(strategyPhase);
  const showPactModal =
    strategyPhase === "submitting_pact" ||
    strategyPhase === "waiting_pact" ||
    isCancelPhase;
  const showFunds = isStrategyActive || isCancelPhase;
  const preview = treasury?.rebalance_preview;
  const supplyBlocked = preview?.action === "hold" && preview.allowed === false;

  return (
    <section className="panel strategy-panel" aria-label="Strategy wallet panel">
      <div className="panel-heading">
        <span>Strategy</span>
        <strong>{treasury?.mode?.includes("sepolia_real") ? "Real Sepolia" : "Local Demo"}</strong>
      </div>

      <div className="strategy-hero">
        <div>
          <span className="strategy-eyebrow">Aave {strategyAsset}</span>
          <h2>安心生息策略</h2>
          <p>
            保留一部分 {strategyAsset} 随时可用，其余放入 Aave 获取基础收益。需要调整时，Agent 会提出
            CAW Rebalance Pact，并只在授权范围内执行。
          </p>
        </div>
        <div className="strategy-actions">
          <button className="primary-action-button" disabled={isBusy || supplyBlocked} onClick={onExecuteStrategy} type="button">
            {getActionButtonLabel(strategyPhase, isBusy, isStrategyActive)}
          </button>
          {isStrategyActive && (
            <button className="danger-action-button" disabled={isBusy} onClick={onCancelStrategy} type="button">
              {getCancelButtonLabel(strategyPhase)}
            </button>
          )}
        </div>
      </div>

      {treasury ? (
        <>
          {treasury.wallet_status?.reason && <p className="empty-state">{treasury.wallet_status.reason}</p>}

          <div className="strategy-status-strip">
            <span>{getStrategyStatusText(strategyPhase, pactStatus, isStrategyActive, yieldBalance, treasury.asset)}</span>
            {pactNeedsRefresh && internalPact && (
              <button
                className="text-button"
                disabled={isBusy}
                onClick={() => onApprovePact(internalPact.pact_id)}
                type="button"
              >
                刷新授权状态
              </button>
            )}
          </div>

          {preview && (
            <section className={`rebalance-preview ${preview.allowed ? "positive" : "blocked"}`} aria-label="Rebalance preview">
              <div>
                <span>Agent 建议</span>
                <strong>{getPreviewAction(preview.action)}</strong>
                <small>{preview.reason}</small>
              </div>
              <div>
                <span>本次金额</span>
                <strong>{preview.amount} {treasury.asset}</strong>
                <small>目标流动性 {preview.liquidity.target} {treasury.asset}</small>
              </div>
              <div>
                <span>预计收益</span>
                <strong>{preview.expected_yield} {treasury.asset}</strong>
                <small>预计持有 {preview.expected_holding_days ?? "n/a"} 天</small>
              </div>
              <div>
                <span>本次预计 Gas</span>
                <strong>{preview.required_native_gas ?? "n/a"} SETH</strong>
                <small>钱包现有 {preview.gas_available ?? treasury.balances.gas_native ?? "0"} SETH</small>
              </div>
              <div>
                <span>净收益</span>
                <strong>{preview.net_benefit} {treasury.asset}</strong>
                <small>已包含 Gas 安全系数</small>
              </div>
            </section>
          )}

          {showFunds ? (
            <section className="funds-overview" aria-label="Current funds">
              <div className="funds-meter">
                <div className="funds-meter-label">
                  <span>当前流动性比例</span>
                  <strong>{liquidityLabel}</strong>
                </div>
                <div className="meter-track" aria-hidden="true">
                  <span style={{ width: liquidityLabel }} />
                </div>
                <small>建议保留 {treasury.recommendation.recommended_liquidity} {treasury.asset} 作为可用资金</small>
              </div>

              <div className="fund-card">
                <span>可用的钱</span>
                <strong>{walletBalance} {treasury.asset}</strong>
                <small>放在钱包里，随时可以使用</small>
              </div>
              <div className="fund-card">
                <span>正在生息</span>
                <strong>{yieldBalance} {treasury.asset}</strong>
                <small>Aave 中的基础收益仓位</small>
              </div>
              <div className="fund-card">
                <span>总资金</span>
                <strong>{totalBalance} {treasury.asset}</strong>
                <small>钱包和 Aave 合计</small>
              </div>
            </section>
          ) : (
            <p className="empty-state">{getPreResultText(strategyPhase)}</p>
          )}
        </>
      ) : (
        <p className="empty-state">点击执行策略后，Agent 会读取钱包状态并提交需要的 Rebalance Pact。</p>
      )}

      {showPactModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="pact-approval-title">
          <div className="approval-modal">
            <span className="loading-dot" aria-hidden="true" />
            <h2 id="pact-approval-title">{getApprovalModalTitle(strategyPhase)}</h2>
            <p>{getApprovalModalText(strategyPhase, yieldBalance, strategyAsset)}</p>
            <small>{pactStatus}</small>
          </div>
        </div>
      )}
    </section>
  );
}

function getPreviewAction(action: string) {
  if (action === "supply_to_aave") {
    return "存入 Aave";
  }
  if (action === "withdraw_from_aave") {
    return "补充钱包流动性";
  }
  return "保持现状";
}

function getPactStatusLabel(status?: string) {
  if (!status) {
    return "尚未提交授权";
  }
  if (status === "pending_owner_approval") {
    return "已提交授权，等待你在 CAW 审批";
  }
  if (status === "active") {
    return "授权已生效，Agent 可在额度内调整";
  }
  if (status === "caw_not_configured") {
    return "CAW 尚未配置";
  }
  return `授权状态：${status}`;
}

function getDisplayInternalPact(treasury: TreasuryState | null) {
  if (!treasury) {
    return undefined;
  }
  const internalPacts = treasury.pacts.filter((pact) => pact.pact_type === "internal_agent_rebalance");
  return (
    internalPacts.find((pact) => pact.status === "active" && pact.caw_pact_id) ??
    [...internalPacts].reverse().find((pact) => pact.caw_pact_id) ??
    [...internalPacts].reverse()[0]
  );
}

function getActionButtonLabel(strategyPhase: StrategyPhase, isBusy: boolean, isStrategyActive: boolean) {
  if (!isBusy) {
    return isStrategyActive ? "重新调整" : "执行策略";
  }
  if (strategyPhase === "submitting_pact") {
    return "提交授权中...";
  }
  if (strategyPhase === "waiting_pact") {
    return "等待审批中...";
  }
  if (strategyPhase === "executing") {
    return "策略执行中...";
  }
  if (["cancel_submitting_pact", "cancel_waiting_pact", "canceling"].includes(strategyPhase)) {
    return "处理中...";
  }
  return "执行策略";
}

function getStrategyStatusText(
  strategyPhase: StrategyPhase,
  pactStatus: string,
  isStrategyActive: boolean,
  yieldBalance: string,
  asset: string,
) {
  if (strategyPhase === "submitting_pact") {
    return "正在向 Cobo Wallet 提交授权请求";
  }
  if (strategyPhase === "waiting_pact") {
    return "等待你在 Cobo App 审批授权";
  }
  if (strategyPhase === "executing") {
    return "授权已通过，正在执行 Aave 策略";
  }
  if (strategyPhase === "completed") {
    return "策略已执行完成";
  }
  if (strategyPhase === "cancel_submitting_pact") {
    return "正在检查撤销策略所需的 CAW Pact";
  }
  if (strategyPhase === "cancel_waiting_pact") {
    return "撤销策略需要新的 CAW Pact，请在 Cobo App 中审批";
  }
  if (strategyPhase === "canceling") {
    return `正在从 Aave 取回 ${yieldBalance} ${asset}`;
  }
  if (isStrategyActive) {
    return `策略运行中，Aave 当前持有 ${yieldBalance} ${asset}`;
  }
  return pactStatus;
}

function getPreResultText(strategyPhase: StrategyPhase) {
  if (strategyPhase === "executing") {
    return "策略执行中，完成后会展示当前流动性比例和可用资金。";
  }
  if (strategyPhase === "completed") {
    return "";
  }
  if (["cancel_submitting_pact", "cancel_waiting_pact", "canceling"].includes(strategyPhase)) {
    return "正在从 Aave 取回资产，完成后这里会回到可执行状态。";
  }
  return "点击执行策略后，Agent 会先提出 Rebalance Pact，等待你审批后再执行 Aave supply。";
}

function getCancelButtonLabel(strategyPhase: StrategyPhase) {
  if (strategyPhase === "cancel_submitting_pact") {
    return "检查授权中...";
  }
  if (strategyPhase === "cancel_waiting_pact") {
    return "等待授权中...";
  }
  if (strategyPhase === "canceling") {
    return "取回资产中...";
  }
  return "取消策略";
}

function getApprovalModalTitle(strategyPhase: StrategyPhase) {
  if (strategyPhase === "submitting_pact") {
    return "正在创建授权请求";
  }
  if (strategyPhase === "waiting_pact") {
    return "需要你在 App 端审核";
  }
  if (strategyPhase === "cancel_submitting_pact") {
    return "正在检查撤销授权";
  }
  if (strategyPhase === "cancel_waiting_pact") {
    return "需要你审批撤销授权";
  }
  if (strategyPhase === "canceling") {
    return "正在撤销策略";
  }
  return "正在处理策略";
}

function getApprovalModalText(
  strategyPhase: StrategyPhase,
  yieldBalance: string,
  asset: string,
) {
  if (strategyPhase === "cancel_submitting_pact") {
    return "Agent 正在检查现有 CAW Rebalance Pact 是否能够覆盖本次全额取回。";
  }
  if (strategyPhase === "cancel_waiting_pact") {
    return "当前没有额度足够的 CAW Rebalance Pact。Agent 已提交新的撤销授权，请在 Cobo App 中审批；通过后将自动继续取回资产。";
  }
  if (strategyPhase === "canceling") {
    return `授权已就绪，Agent 正在从 Aave 取回 ${yieldBalance} ${asset}，请等待链上确认。`;
  }
  return "Agent 正在向 Cobo Wallet 提交本策略需要的 Rebalance Pact。请在 Cobo App 中确认并通过，前端会自动检测授权状态，通过后继续执行 Aave 策略。";
}
