import { TreasuryPlan } from "../api";

type TreasuryPlanCardProps = {
  plan: TreasuryPlan;
  isBusy: boolean;
  onSelect: (planId: string, scenarioId: string) => Promise<void>;
};

const ACTION_LABELS = {
  supply_to_aave: "Supply to Aave",
  withdraw_from_aave: "Withdraw from Aave",
  hold: "Hold",
};

export function TreasuryPlanCard({
  plan,
  isBusy,
  onSelect,
}: TreasuryPlanCardProps) {
  return (
    <article className="treasury-plan-card" aria-label="Treasury plan scenarios">
      <div className="planner-card-heading">
        <div>
          <span>Deterministic simulations</span>
          <h2>选择资金目标，不是授权交易</h2>
        </div>
        <b>3 scenarios</b>
      </div>

      <div className="scenario-grid">
        {plan.scenarios.map((scenario) => {
          const action = ACTION_LABELS[scenario.expected_action.action];
          return (
            <section className="scenario-option" key={scenario.scenario_id}>
              <div className="scenario-index">
                <span>{scenario.scenario_id.replace("_", " ")}</span>
                <strong>{scenario.label}</strong>
              </div>

              <dl>
                <div>
                  <dt>保留流动性</dt>
                  <dd>{scenario.after.recommended_liquidity} WBTC</dd>
                </div>
                <div>
                  <dt>主导约束</dt>
                  <dd>{candidateLabel(scenario.after.dominant_candidate)}</dd>
                </div>
                <div>
                  <dt>Aave 目标</dt>
                  <dd>{scenario.after.target_yield_balance} WBTC</dd>
                </div>
                <div>
                  <dt>经常性 P90</dt>
                  <dd>{scenario.recurring_statistics.recurring_p90_transfer_amount} WBTC</dd>
                </div>
                <div>
                  <dt>预计动作</dt>
                  <dd>{action} {scenario.expected_action.amount} WBTC</dd>
                </div>
              </dl>

              <div className={`pact-gap ${scenario.pact_gap.requires_new_pact ? "open" : "covered"}`}>
                <span>Pact gap</span>
                <strong>
                  {scenario.pact_gap.requires_new_pact
                    ? `${scenario.pact_gap.additional_limit_required} WBTC`
                    : "Covered"}
                </strong>
              </div>

              {scenario.planned_outflows.length > 0 && (
                <p className="scenario-outflow">
                  Planned: {scenario.planned_outflows.map((item) => `${item.amount} WBTC`).join(" + ")}
                </p>
              )}

              <button
                className="primary-action-button"
                disabled={isBusy}
                onClick={() => void onSelect(plan.plan_id, scenario.scenario_id)}
                type="button"
              >
                {isBusy ? "Applying..." : `选择${scenario.label}`}
              </button>
            </section>
          );
        })}
      </div>

      <p className="planner-boundary-note">{plan.safety_boundary}</p>
    </article>
  );
}

function candidateLabel(value?: string) {
  const labels: Record<string, string> = {
    user_floor: "用户最低保留",
    min_liquidity_ratio: "最低安全比例",
    flow_horizon: "经常性流出",
    recurring_single_buffer: "经常性 P90",
    planned_outflow: "计划支出",
    economic_batch: "Gas 经济批量",
  };
  return value ? labels[value] ?? value : "系统计算";
}
