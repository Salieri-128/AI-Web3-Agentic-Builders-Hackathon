import { FormEvent, useState } from "react";
import { MemoryProposal } from "../api";
import { MemoryProposalCard } from "./MemoryProposalCard";

export type ChatTurn = {
  role: "user" | "agent";
  content: string;
  llmUsed?: boolean;
  cawUsed?: boolean;
  memoryUpdated?: boolean;
};

type ChatPanelProps = {
  messages: ChatTurn[];
  isSending: boolean;
  pendingText?: string;
  onSend: (message: string) => Promise<void>;
  memoryProposal?: MemoryProposal | null;
  isMemoryBusy?: boolean;
  onConfirmMemory: (proposalId: string) => Promise<void>;
  onRejectMemory: (proposalId: string) => Promise<void>;
};

export function ChatPanel({
  messages,
  isSending,
  pendingText,
  onSend,
  memoryProposal,
  isMemoryBusy = false,
  onConfirmMemory,
  onRejectMemory,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const quickPrompts = [
    "分析我的资金并给出流动性建议",
    "解释当前 Aave 策略和风险",
    "查看我最近的资金管理偏好",
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
    <section className="chat-panel-wide" aria-label="Chat panel">
      <div className="message-list">
        {messages.length > 0 ? (
          <>
            {messages.map((message, index) => (
              <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
                <div className="message-meta">
                  <span>{message.role === "agent" ? "Agent" : "You"}</span>
                  {message.llmUsed && <b>LLM Used</b>}
                  {message.cawUsed && <b>CAW Used</b>}
                  {message.memoryUpdated && <b>Memory Updated</b>}
                </div>
                <p>{message.content}</p>
              </article>
            ))}
            {isSending && (
              <article className="message agent pending">
                <div className="message-meta">
                  <span>Agent</span>
                  <b>Thinking</b>
                </div>
                <p>{pendingText || "正在处理请求..."}</p>
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
          </>
        ) : (
          <div className="chat-empty-state">
            <div className="agent-signal" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <span className="empty-eyebrow">CAW secured agent</span>
            <h2>What should your treasury do next?</h2>
            <p>
              Describe a goal in plain language. The agent can analyze and propose actions, while every execution remains
              constrained by an owner-approved Pact.
            </p>
            <div className="quick-prompts" aria-label="Suggested prompts">
              {quickPrompts.map((prompt, index) => (
                <button disabled={isSending} key={prompt} onClick={() => void onSend(prompt)} type="button">
                  <span>0{index + 1}</span>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <form className="chat-form" onSubmit={submit}>
        <div className="chat-input-wrap">
          <span className="command-prefix" aria-hidden="true">&gt;_</span>
          <input
            aria-label="Message"
            placeholder="Ask the treasury agent..."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <small>Pact approval is always required outside the current authorization.</small>
        </div>
        <button disabled={isSending} type="submit">
          <span>{isSending ? "Working" : "Run command"}</span>
          <b aria-hidden="true">↗</b>
        </button>
      </form>
    </section>
  );
}
