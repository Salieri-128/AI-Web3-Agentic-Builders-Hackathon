import { FormEvent, useEffect, useRef, useState } from "react";

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
  walletAddress?: string | null;
  asset?: string;
  onOpenOptimization: () => void;
};

export function ChatPanel({
  messages,
  isSending,
  pendingText,
  onSend,
  walletAddress,
  asset = "WBTC",
  onOpenOptimization,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [walletAction, setWalletAction] = useState<"receive" | "transfer" | null>(null);
  const [transferAmount, setTransferAmount] = useState("");
  const [transferAddress, setTransferAddress] = useState("");
  const [transferError, setTransferError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const messageList = messageListRef.current;
    if (!messageList) {
      return;
    }
    const frameId = window.requestAnimationFrame(() => {
      messageList.scrollTop = messageList.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [messages.length, isSending, pendingText, walletAction]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) {
      return;
    }
    setDraft("");
    await onSend(message);
  }

  async function submitTransfer(event: FormEvent) {
    event.preventDefault();
    const amount = transferAmount.trim();
    const destination = transferAddress.trim();
    if (!/^\d+(?:\.\d{1,8})?$/.test(amount) || Number(amount) <= 0) {
      setTransferError("请输入大于 0、最多 8 位小数的 WBTC 金额。");
      return;
    }
    if (!/^0x[a-fA-F0-9]{40}$/.test(destination)) {
      setTransferError("请输入有效的 EVM 收款地址。");
      return;
    }
    setTransferError(null);
    await onSend(`转账 ${amount} ${asset} 到 ${destination}`);
    setWalletAction(null);
  }

  async function copyAddress() {
    if (!walletAddress) {
      return;
    }
    try {
      await navigator.clipboard.writeText(walletAddress);
      setCopyStatus("地址已复制");
    } catch {
      const textArea = document.createElement("textarea");
      textArea.value = walletAddress;
      textArea.style.position = "fixed";
      textArea.style.opacity = "0";
      document.body.appendChild(textArea);
      textArea.select();
      const copied = document.execCommand("copy");
      textArea.remove();
      setCopyStatus(copied ? "地址已复制" : "复制失败，请手动复制");
    }
  }

  return (
    <section className="chat-panel-wide" aria-label="Chat panel">
      <div className="message-list" ref={messageListRef}>
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
            <div className="wallet-action-strip" aria-label="Wallet shortcuts">
              <button disabled={isSending} onClick={() => void onSend("查看钱包余额")} type="button">
                查看余额
              </button>
              <button
                disabled={isSending}
                onClick={() => {
                  setCopyStatus(null);
                  setWalletAction("receive");
                }}
                type="button"
              >
                收款
              </button>
              <button disabled={isSending} onClick={() => setWalletAction("transfer")} type="button">
                转账
              </button>
              <button disabled={isSending} onClick={onOpenOptimization} type="button">
                资金优化
              </button>
            </div>
          </>
        ) : (
          <div className="chat-empty-state">
            <div className="agent-signal" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <span className="empty-eyebrow">CAW secured wallet</span>
            <h2>今天想用钱包做什么？</h2>
            <p>
              查看余额、收款或安全转账。资金统计在后台自动完成，不需要配置流动性参数。
            </p>
            <div className="wallet-actions" aria-label="Wallet actions">
              <button disabled={isSending} onClick={() => void onSend("查看钱包余额")} type="button">
                <span>01</span>
                <strong>查看余额</strong>
                <small>钱包、Gas 与 Aave 仓位</small>
              </button>
              <button disabled={isSending} onClick={() => setWalletAction("receive")} type="button">
                <span>02</span>
                <strong>收款</strong>
                <small>显示 Sepolia {asset} 地址</small>
              </button>
              <button disabled={isSending} onClick={() => setWalletAction("transfer")} type="button">
                <span>03</span>
                <strong>转账</strong>
                <small>余额检查与 Pact 保护</small>
              </button>
              <button className="optimization-entry" onClick={onOpenOptimization} type="button">
                <span>04</span>
                <strong>资金优化</strong>
                <small>可选的收益与流动性规划</small>
              </button>
            </div>
          </div>
        )}

        {walletAction === "receive" && (
          <article className="receive-card" aria-label="Receive WBTC">
            <div>
              <span>Receive on Sepolia</span>
              <h2>收取 {asset}</h2>
              <p>只向下方 EVM 地址发送 Sepolia 网络上的 {asset}。</p>
            </div>
            <code>{walletAddress || "钱包地址暂不可用，请先 Sync now。"}</code>
            <div className="wallet-card-actions">
              <button disabled={!walletAddress} onClick={() => void copyAddress()} type="button">
                复制地址
              </button>
              <button onClick={() => setWalletAction(null)} type="button">关闭</button>
            </div>
            {copyStatus && <small role="status">{copyStatus}</small>}
          </article>
        )}

        {walletAction === "transfer" && (
          <article className="transfer-form-card" aria-label="Transfer WBTC">
            <div>
              <span>Protected transfer</span>
              <h2>发送 {asset}</h2>
              <p>提交后，后端会检查余额、Aave 流动性和当前 CAW Pact。</p>
            </div>
            <form onSubmit={submitTransfer}>
              <label>
                金额
                <div className="amount-input">
                  <input
                    aria-label="Transfer amount"
                    inputMode="decimal"
                    placeholder="0.01"
                    value={transferAmount}
                    onChange={(event) => setTransferAmount(event.target.value)}
                  />
                  <strong>{asset}</strong>
                </div>
              </label>
              <label>
                收款地址
                <input
                  aria-label="Transfer destination"
                  placeholder="0x..."
                  value={transferAddress}
                  onChange={(event) => setTransferAddress(event.target.value)}
                />
              </label>
              {transferError && <p className="form-error" role="alert">{transferError}</p>}
              <div className="wallet-card-actions">
                <button disabled={isSending} type="submit">
                  {isSending ? "检查中..." : "检查并发送"}
                </button>
                <button onClick={() => setWalletAction(null)} type="button">取消</button>
              </div>
            </form>
          </article>
        )}
      </div>

      <form className="chat-form" onSubmit={submit}>
        <div className="chat-input-wrap">
          <span className="command-prefix" aria-hidden="true">&gt;_</span>
          <input
            aria-label="Message"
            placeholder="也可以直接输入：查看余额、转账，或描述资金目标"
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
