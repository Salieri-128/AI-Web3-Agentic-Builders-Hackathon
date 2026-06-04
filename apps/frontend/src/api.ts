export type StatusResponse = {
  backend: string;
  agent: string;
  caw_configured: boolean;
  memory_loaded: boolean;
};

export type Profile = {
  user_preferences?: {
    cash_buffer_usdc?: string | number | null;
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
  type: string;
  asset: string;
  amount: string;
  destination: string;
  status: string;
  execution_enabled: boolean;
  reason: string;
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
  caw_used: boolean;
  memory_updated: boolean;
  proposal: Proposal | null;
  audit_logs: AuditLog[];
  profile: Profile | null;
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
