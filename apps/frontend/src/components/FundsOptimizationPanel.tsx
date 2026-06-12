import { FormEvent, useState } from "react";
import {
  Clarification,
  MemoryProposal,
  Profile,
  TransferClassificationProposal,
  TreasuryPlan,
  TreasuryState,
} from "../api";
import { ChatTurn } from "./ChatPanel";
import { MemoryProposalCard } from "./MemoryProposalCard";
import { StrategyDataPanel } from "./StrategyDataPanel";
import { TransferClassificationCard } from "./TransferClassificationCard";
import { TreasuryPanel, StrategyPhase } from "./TreasuryPanel";
import { TreasuryPlanCard } from "./TreasuryPlanCard";

type FundsOptimizationPanelProps = {
  messages: ChatTurn[];
  strategyActive: boolean;
  isSending: boolean;
  onSend: (message: string) => Promise<void>;
  profile: Profile | null;
  treasury: TreasuryState | null;
  memoryProposal?: MemoryProposal | null;
  clarification?: Clarification | null;
  treasuryPlan?: TreasuryPlan | null;
  transferClassificationProposal?: TransferClassificationProposal | null;
  isMemoryBusy: boolean;
  isPlannerBusy: boolean;
  isTreasuryBusy: boolean;
  strategyPhase: StrategyPhase;
  onConfirmMemory: (proposalId: string) => Promise<void>;
  onRejectMemory: (proposalId: string) => Promise<void>;
  onSelectTreasuryPlan: (planId: string, scenarioId: string) => Promise<void>;
  onConfirmTransferClassification: (proposalId: string) => Promise<void>;
  onRejectTransferClassification: (proposalId: string) => Promise<void>;
  onExecuteStrategy: () => void;
  onCancelStrategy: () => void;
  onApprovePact: (pactId: string) => void;
};

export function FundsOptimizationPanel({
  messages,
  strategyActive,
  isSending,
  onSend,
  profile,
  treasury,
  memoryProposal,
  clarification,
  treasuryPlan,
  transferClassificationProposal,
  isMemoryBusy,
  isPlannerBusy,
  isTreasuryBusy,
  strategyPhase,
  onConfirmMemory,
  onRejectMemory,
  onSelectTreasuryPlan,
  onConfirmTransferClassification,
  onRejectTransferClassification,
  onExecuteStrategy,
  onCancelStrategy,
  onApprovePact,
}: FundsOptimizationPanelProps) {
  const [draft, setDraft] = useState("");
  const plannerMessages = messages;
  const prompts = [
    "提高收益，但保留足够日常流动性",
    "下周有一笔 0.2 WBTC 支出",
    "策略更保守一点",
  ];

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) {
      return;
    }
    setDraft("");
    await onSend(message);
  }

  return (
    <section className="funds-optimization-layout" aria-label="Funds optimization">
      <TreasuryPanel
        treasury={treasury}
        isBusy={isTreasuryBusy}
        strategyPhase={strategyPhase}
        onExecuteStrategy={onExecuteStrategy}
        onCancelStrategy={onCancelStrategy}
        onApprovePact={onApprovePact}
      />

      {strategyActive ? (
        <section className="optimization-unlocked" aria-label="Unlocked funds optimization">
          <section className="panel optimization-command">
            <div className="optimization-command-copy">
              <span>Strategy active / AI planning unlocked</span>
              <h2>告诉 Agent 你的资金优化目标</h2>
              <p>
                策略已经运行。你现在可以调整收益与流动性目标；所有金额由后端计算，任何资金动作仍受 CAW Pact 约束。
              </p>
            </div>

            <div className="optimization-prompts">
              {prompts.map((prompt) => (
                <button disabled={isSending} key={prompt} onClick={() => void onSend(prompt)} type="button">
                  {prompt}
                </button>
              ))}
            </div>

            <form className="optimization-form" onSubmit={submit}>
              <input
                aria-label="Funds optimization goal"
                placeholder="例如：下周要付款，同时尽量提高闲置资金收益"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button disabled={isSending} type="submit">
                {isSending ? "Planning..." : "生成方案"}
              </button>
            </form>
          </section>

          {plannerMessages.length > 0 && (
            <section className="optimization-conversation" aria-label="Optimization conversation">
              {plannerMessages.map((message, index) => (
                <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
                  <div className="message-meta">
                    <span>{message.role === "agent" ? "Agent" : "You"}</span>
                    {message.llmUsed && <b>LLM Used</b>}
                  </div>
                  <p>{message.content}</p>
                </article>
              ))}
            </section>
          )}

          {clarification && (
            <article className="clarification-card" aria-label="Agent clarification">
              <span>Clarification required</span>
              <strong>{clarification.question}</strong>
              <small>回答只会继续规划，不会执行转账或修改 Pact。</small>
              {clarification.missing_information.includes("risk_adjustment_priority") && (
                <div className="clarification-actions">
                  <button
                    disabled={isSending}
                    onClick={() => void onSend("改成激进策略，优先降低最低保留比例")}
                    type="button"
                  >
                    优先降低保留比例
                  </button>
                  <button
                    disabled={isSending}
                    onClick={() => void onSend("改成激进策略，流动性覆盖 3 天")}
                    type="button"
                  >
                    缩短覆盖到 3 天
                  </button>
                </div>
              )}
            </article>
          )}

          {memoryProposal && (
            <MemoryProposalCard
              proposal={memoryProposal}
              isBusy={isMemoryBusy}
              onConfirm={onConfirmMemory}
              onReject={onRejectMemory}
            />
          )}

          {treasuryPlan && (
            <TreasuryPlanCard
              plan={treasuryPlan}
              isBusy={isPlannerBusy}
              onSelect={onSelectTreasuryPlan}
            />
          )}

          {transferClassificationProposal && (
            <TransferClassificationCard
              proposal={transferClassificationProposal}
              isBusy={isPlannerBusy}
              onConfirm={onConfirmTransferClassification}
              onReject={onRejectTransferClassification}
            />
          )}

          <details className="advanced-policy-details">
            <summary>
              <span>Advanced decision data</span>
              查看画像、稳健统计和公式参数
            </summary>
            <StrategyDataPanel profile={profile} treasury={treasury} />
          </details>
        </section>
      ) : (
        <aside className="optimization-locked-note" aria-label="Funds optimization locked">
          <span>Step 02 locked</span>
          <strong>执行策略后，再设置资金优化目标</strong>
          <p>先完成上方 Aave 策略与 CAW Pact 流程。策略运行后，AI Planner、画像调整和高级决策数据会在这里解锁。</p>
        </aside>
      )}
    </section>
  );
}
