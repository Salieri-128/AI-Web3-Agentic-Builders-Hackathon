export type StatusResponse = {
  backend: string;
  agent: string;
  caw_configured: boolean;
  llm_configured: boolean;
  memory_loaded: boolean;
};

export type Profile = {
  user_preferences?: {
    cash_buffer_usdc?: string | number | null;
    liquidity_floor?: string | number | null;
    risk_level?: string;
    preferred_assets?: string[];
    blocked_assets?: string[];
    whitelisted_addresses?: string[];
  };
  transaction_habits?: {
    prefers_low_gas?: boolean;
    requires_confirmation_before_execution?: boolean;
  };
  notes?: string[];
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
  proposal: Proposal | null;
  wallet: WalletStatus | null;
  audit_logs: AuditLog[];
  profile: Profile | null;
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
  transfer_stats_7d: {
    weekly_transfer_count: number;
    weekly_transfer_sum: string;
    weekly_max_single_amount: string;
    weekly_avg_transfer_amount: string;
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

export async function sendChat(message: string): Promise<ChatResponse> {
  const response = await fetch(`${backendUrl}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    throw new Error("Failed to send message to backend agent");
  }
  return response.json();
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
