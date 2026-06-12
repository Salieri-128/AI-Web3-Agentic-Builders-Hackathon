export type StatusResponse = {
  backend: string;
  agent: string;
  caw_configured: boolean;
  llm_configured: boolean;
  memory_loaded: boolean;
};

export type Profile = {
  user_preferences?: {
    liquidity_floor?: string | number | null;
    liquidity_horizon_days?: number | null;
    risk_level?: "conservative" | "balanced" | "aggressive";
  };
  transaction_habits?: {
    prefers_low_gas?: boolean;
  };
};

export type MemoryProposal = {
  proposal_id: string;
  status: string;
  message: string;
  patch: Record<string, string | number | boolean | null>;
  changes: Array<{
    field: string;
    before: string | number | boolean | null;
    after: string | number | boolean | null;
  }>;
  liquidity_impact: {
    asset: string;
    changed: boolean;
    before: LiquidityImpact;
    after: LiquidityImpact;
    strategy_history?: {
      recurring_transfer_sum: string;
      recurring_p90_transfer_amount: string;
      excluded_transfer_count: number;
      excluded_transfers: TransferClassification[];
    };
  };
};

export type LiquidityImpact = {
  recommended_liquidity: string;
  target_yield_balance: string;
  candidates: Record<string, string>;
  effective_strategy: Record<string, string | number>;
  dominant_candidate?: string;
};

export type Clarification = {
  planning_session_id: string;
  question: string;
  missing_information: string[];
  confidence: number;
  candidates?: TransferClassification[];
};

export type TreasuryScenario = {
  scenario_id: string;
  label: string;
  profile_patch: Record<string, string | number | boolean | null>;
  planned_outflows: PlannedOutflow[];
  before: LiquidityImpact;
  after: LiquidityImpact;
  recurring_statistics: {
    recurring_transfer_sum: string;
    recurring_p90_transfer_amount: string;
    excluded_transfer_count: number;
  };
  expected_action: {
    action: "supply_to_aave" | "withdraw_from_aave" | "hold";
    amount: string;
  };
  pact_gap: {
    active_internal_limit: string;
    additional_limit_required: string;
    requires_new_pact: boolean;
  };
};

export type PlannedOutflow = {
  amount: string;
  due_at: string;
  description?: string;
};

export type TreasuryPlan = {
  plan_id: string;
  planning_session_id: string;
  status: string;
  message: string;
  explanation: string;
  scenarios: TreasuryScenario[];
  safety_boundary: string;
};

export type TransferClassification = {
  event_id: string;
  amount: string;
  created_at?: string;
  destination?: string;
  classification: "one_off" | "recurring";
  source: "automatic" | "user";
  reason: string;
};

export type TransferClassificationProposal = {
  proposal_id: string;
  status: string;
  classification: "one_off" | "recurring";
  event: TransferClassification;
  statistics_before: StrategyTransferStats;
  statistics_after: StrategyTransferStats;
  safety_boundary: string;
};

type StrategyTransferStats = {
  recurring_transfer_sum: string;
  recurring_p90_transfer_amount: string;
  one_off_transfer_sum: string;
  excluded_transfer_count: number;
};

export type ClassificationEffect = {
  recommended_liquidity: string;
  target_yield_balance: string;
  action: "supply_to_aave" | "withdraw_from_aave" | "hold";
  amount: string;
  requires_new_pact: boolean;
};

export type ClassificationAttention = {
  event: TransferClassification;
  automatic_classification: "one_off";
  alternative_classification: "recurring";
  needs_attention: boolean;
  threshold: string;
  impact: {
    liquidity_delta: string;
    action_changed: boolean;
    pact_gap_changed: boolean;
    one_off: ClassificationEffect;
    recurring: ClassificationEffect;
  };
};

export type Proposal = {
  type?: string;
  pact_id?: string;
  pact_type?: string;
  asset?: string;
  amount?: string;
  destination?: string;
  chain_id?: string;
  status: string;
  execution_enabled?: boolean;
  reason: string;
  scope?: Record<string, unknown>;
  pact_spec?: Record<string, unknown>;
  pact_submission?: Record<string, unknown>;
  execution_result?: Record<string, unknown>;
};

export type AuditLog = {
  action?: string;
  result?: string;
  created_at?: string;
  reason?: string;
  request_id?: string;
};

export type ChatResponse = {
  reply: string;
  llm_used: boolean;
  caw_used: boolean;
  memory_updated: boolean;
  memory_proposal?: MemoryProposal | null;
  proposal: Proposal | null;
  wallet: WalletStatus | null;
  audit_logs: AuditLog[];
  profile: Profile | null;
  planning_session_id?: string | null;
  clarification?: Clarification | null;
  treasury_plan?: TreasuryPlan | null;
  transfer_classification_proposal?: TransferClassificationProposal | null;
};

export type WalletStatus = {
  reason?: string;
  wallet?: Record<string, string | number | boolean | null>;
  addresses?: Array<Record<string, string | number | boolean | null>>;
  balances?: Array<Record<string, string | number | boolean | null>>;
};

export type LocalPact = {
  pact_id: string;
  caw_pact_id?: string | null;
  pact_type: "internal_agent_rebalance" | "external_transfer";
  status: string;
  scope: Record<string, string | number | boolean | string[]>;
  duration: string;
  reason: string;
  created_at: string;
};

export type TreasuryState = {
  mode?: string;
  wallet_id: string;
  asset: string;
  chain_id: string;
  balances: {
    wallet_available?: string;
    aave_withdrawable?: string;
    gas_native?: string;
    wallet: string;
    yield?: string;
    aave?: string;
    total: string;
  };
  strategy: Record<string, string | number>;
  base_strategy?: Record<string, string | number>;
  effective_strategy?: Record<string, string | number>;
  profile_impacts?: Array<{
    profile_field: string;
    strategy_field: string;
    before: string | number;
    after: string | number;
  }>;
  candidate_sources?: Record<string, string>;
  classification_attention?: ClassificationAttention | null;
  transfer_stats_7d: {
    transfer_count: number;
    transfer_sum: string;
    p95_transfer_amount: string;
    weekly_transfer_count: number;
    weekly_transfer_sum: string;
    weekly_max_single_amount: string;
    weekly_avg_transfer_amount: string;
    recurring_transfer_sum: string;
    recurring_p90_transfer_amount: string;
    one_off_transfer_sum: string;
    excluded_transfer_count: number;
    automatic_outlier_threshold?: string | null;
    transfer_classifications: TransferClassification[];
  };
  recommendation: {
    recommended_liquidity: string;
    target_yield_balance?: string;
    target_aave_balance?: string;
    candidates: Record<string, string>;
    formula: string;
  };
  liquidity?: {
    target: string;
    target_yield_balance: string;
    components: Record<string, string>;
    current_ratio: string;
    average_daily_outflow: string;
    annual_outflow: string;
    formula: string;
  };
  rebalance_preview?: RebalancePreview | null;
  pending_transfer?: {
    id?: string;
    stage: string;
    status?: string;
    destination: string;
    amount: string;
    withdraw_amount?: string;
    reason?: string;
    retryable?: boolean;
  } | null;
  pacts: LocalPact[];
  aave?: {
    status?: string;
    asset?: string;
    a_token_asset?: string;
    wallet_address?: string;
    wallet_balance?: string;
    aave_balance?: string;
    pool_allowance?: string;
  };
  wallet_status?: WalletStatus;
  last_rebalance_at?: string | null;
  updated_at?: string | null;
};

export type RebalancePreview = {
  action: "supply_to_aave" | "withdraw_from_aave" | "hold";
  allowed: boolean;
  amount: string;
  expected_holding_days?: string;
  expected_yield: string;
  round_trip_gas?: string;
  guarded_gas?: string;
  net_benefit: string;
  reason: string;
  gas_available?: string;
  required_native_gas?: string;
  estimated_fees?: {
    token_id?: string;
    amounts_native?: Record<string, string>;
    amounts_wbtc?: Record<string, string>;
    prices?: Record<string, string>;
    prices_available?: boolean;
  };
  liquidity: NonNullable<TreasuryState["liquidity"]>;
};

export type WorkspaceSyncResult = {
  status: string;
  synced_at: string;
  incoming_amount: string;
  profile: Profile;
  treasury: TreasuryState;
  preview: RebalancePreview;
  system_status: StatusResponse;
};

const backendUrl = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetch(`${backendUrl}/api/status`);
  if (!response.ok) {
    throw new Error("Failed to load backend status");
  }
  return response.json();
}

export async function fetchProfile(): Promise<Profile> {
  const response = await fetch(`${backendUrl}/api/profile`);
  if (!response.ok) {
    throw new Error("Failed to load memory profile");
  }
  return response.json();
}

export async function confirmMemoryProposal(proposalId: string): Promise<{
  proposal: MemoryProposal;
  profile: Profile;
  treasury: TreasuryState;
}> {
  return updateMemoryProposal("confirm", proposalId);
}

export async function rejectMemoryProposal(proposalId: string): Promise<{
  proposal: MemoryProposal;
  profile: Profile;
}> {
  return updateMemoryProposal("reject", proposalId);
}

async function updateMemoryProposal(action: "confirm" | "reject", proposalId: string) {
  const response = await fetch(`${backendUrl}/api/profile/proposals/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  if (!response.ok) {
    throw new Error(`Failed to ${action} memory proposal`);
  }
  const payload = await response.json();
  return payload.data;
}

export async function sendChat(
  message: string,
  planningSessionId?: string | null,
): Promise<ChatResponse> {
  const response = await fetch(`${backendUrl}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      planning_session_id: planningSessionId || undefined,
    }),
  });
  if (!response.ok) {
    throw new Error("Failed to send message to backend agent");
  }
  return response.json();
}

export async function selectTreasuryPlan(
  planId: string,
  scenarioId: string,
): Promise<{
  plan: TreasuryPlan;
  profile: Profile;
  treasury: TreasuryState;
}> {
  const response = await fetch(`${backendUrl}/api/treasury/plans/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id: planId, scenario_id: scenarioId }),
  });
  if (!response.ok) {
    throw new Error("Failed to apply treasury scenario");
  }
  const payload = await response.json();
  return payload.data;
}

export async function confirmTransferClassification(
  proposalId: string,
): Promise<{
  proposal: TransferClassificationProposal;
  profile: Profile;
  treasury: TreasuryState;
}> {
  return updateTransferClassification("confirm", proposalId);
}

export async function rejectTransferClassification(
  proposalId: string,
): Promise<{ proposal: TransferClassificationProposal }> {
  return updateTransferClassification("reject", proposalId);
}

export async function applyTransferClassification(
  eventId: string,
  classification: "one_off" | "recurring",
): Promise<{
  classification: Record<string, unknown>;
  profile: Profile;
  treasury: TreasuryState;
}> {
  const response = await fetch(`${backendUrl}/api/transfers/classifications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_id: eventId,
      classification,
    }),
  });
  if (!response.ok) {
    throw new Error("Failed to apply transfer classification");
  }
  const payload = await response.json();
  return payload.data;
}

async function updateTransferClassification(
  action: "confirm" | "reject",
  proposalId: string,
) {
  const response = await fetch(
    `${backendUrl}/api/transfers/classifications/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_id: proposalId }),
    },
  );
  if (!response.ok) {
    throw new Error(`Failed to ${action} transfer classification`);
  }
  const payload = await response.json();
  return payload.data;
}

export async function fetchWalletStatus(): Promise<WalletStatus> {
  const response = await fetch(`${backendUrl}/api/caw/wallet`);
  if (!response.ok) {
    throw new Error("Failed to load CAW wallet status");
  }
  const payload = await response.json();
  return payload.data;
}

export async function fetchTreasuryState(): Promise<TreasuryState> {
  const response = await fetch(`${backendUrl}/api/treasury`);
  if (!response.ok) {
    throw new Error("Failed to load treasury state");
  }
  const payload = await response.json();
  return payload.data;
}

export async function initializeTreasury(depositAmount = "1000"): Promise<TreasuryState> {
  const response = await fetch(`${backendUrl}/api/treasury/initialize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deposit_amount: depositAmount }),
  });
  if (!response.ok) {
    throw new Error("Failed to initialize treasury wallet");
  }
  const payload = await response.json();
  return payload.data;
}

export async function rebalanceTreasury(): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/treasury/rebalance`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to run rebalance");
  }
  const payload = await response.json();
  return payload.data;
}

export async function previewTreasuryRebalance(): Promise<RebalancePreview> {
  const response = await fetch(`${backendUrl}/api/treasury/rebalance/preview`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to preview rebalance");
  }
  const payload = await response.json();
  return payload.data;
}

export async function syncTreasury(): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/treasury/sync`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to sync treasury balances");
  }
  const payload = await response.json();
  return payload.data;
}

export async function syncWorkspace(): Promise<WorkspaceSyncResult> {
  const response = await fetch(`${backendUrl}/api/workspace/sync`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to synchronize workspace");
  }
  const payload = await response.json();
  return payload.data;
}

export async function executePendingTransfer(): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/treasury/transfers/pending/execute`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to check pending transfer");
  }
  const payload = await response.json();
  return payload.data;
}

export async function fetchPendingTransferStatus(): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/treasury/transfers/pending/status`);
  if (!response.ok) {
    throw new Error("Failed to load pending transfer status");
  }
  const payload = await response.json();
  return payload.data;
}

export async function approveTreasuryPact(pactId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/treasury/pacts/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pact_id: pactId }),
  });
  if (!response.ok) {
    throw new Error("Failed to approve local pact");
  }
  const payload = await response.json();
  return payload.data;
}

export async function submitAavePact(maxAmount = "100"): Promise<Record<string, unknown>> {
  const response = await fetch(`${backendUrl}/api/aave/pacts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_amount: maxAmount }),
  });
  if (!response.ok) {
    throw new Error("Failed to submit Aave pact");
  }
  const payload = await response.json();
  return payload.data;
}

export async function supplyAave(pactId: string, amount = "10"): Promise<Record<string, unknown>> {
  return runAaveAction("supply", pactId, amount);
}

export async function withdrawAave(pactId: string, amount = "10"): Promise<Record<string, unknown>> {
  return runAaveAction("withdraw", pactId, amount);
}

async function runAaveAction(action: "supply" | "withdraw", pactId: string, amount: string) {
  const response = await fetch(`${backendUrl}/api/aave/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pact_id: pactId, amount }),
  });
  if (!response.ok) {
    throw new Error(`Failed to run Aave ${action}`);
  }
  const payload = await response.json();
  return payload.data;
}
