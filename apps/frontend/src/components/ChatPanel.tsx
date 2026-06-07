import { FormEvent, useState } from "react";

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
  onSend: (message: string) => Promise<void>;
};

export function ChatPanel({ messages, isSending, onSend }: ChatPanelProps) {
  const [draft, setDraft] = useState("");

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
                <p>正在理解你的问题，并调用可用工具查询结果...</p>
              </article>
            )}
          </>
        ) : (
          <div className="chat-empty-state" />
        )}
      </div>

      <form className="chat-form" onSubmit={submit}>
        <input
          aria-label="Message"
          placeholder="Ask the treasury agent..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button disabled={isSending} type="submit">
          {isSending ? "Sending" : "Send"}
        </button>
      </form>
    </section>
  );
}
