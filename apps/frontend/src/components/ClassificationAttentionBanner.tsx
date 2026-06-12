import { ClassificationAttention } from "../api";

type ClassificationAttentionBannerProps = {
  attention: ClassificationAttention;
  isBusy: boolean;
  onClassify: (eventId: string, classification: "one_off" | "recurring") => Promise<void>;
};

export function ClassificationAttentionBanner({
  attention,
  isBusy,
  onClassify,
}: ClassificationAttentionBannerProps) {
  return (
    <aside className="classification-attention" aria-label="Transfer classification attention">
      <div>
        <span>资金优化提示</span>
        <strong>
          {attention.event.amount} WBTC 可能是一次性转账
        </strong>
        <p>
          如果它会经常发生，建议保留将从{" "}
          {attention.impact.one_off.recommended_liquidity} 调整为{" "}
          {attention.impact.recurring.recommended_liquidity} WBTC。此选择只影响后台建议。
        </p>
      </div>
      <div className="classification-attention-actions">
        <button
          disabled={isBusy}
          onClick={() => void onClassify(attention.event.event_id, "one_off")}
          type="button"
        >
          确认一次性
        </button>
        <button
          disabled={isBusy}
          onClick={() => void onClassify(attention.event.event_id, "recurring")}
          type="button"
        >
          视为经常性
        </button>
      </div>
    </aside>
  );
}
