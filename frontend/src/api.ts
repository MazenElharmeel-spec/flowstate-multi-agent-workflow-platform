export const API = import.meta.env.VITE_API_URL ?? '/api/v1';
export type User = { id: string; email: string; role: string };
export type Run = {
  id: string;
  workflow_definition_id: string;
  workflow_version: number;
  status: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  current_node: string | null;
  step_count: number;
  total_tokens: number;
  estimated_cost_usd: number;
  created_at: string;
};
export type Workflow = {
  id: string;
  key: string;
  version: number;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
};
export type Approval = {
  id: string;
  run_id: string;
  tool_name: string;
  original_arguments: Record<string, unknown>;
  resolved_arguments: Record<string, unknown>;
  risk_level: string;
  reason: string;
  status: string;
  expires_at: string;
};
export type Event = {
  id: string;
  sequence_number: number;
  event_type: string;
  node_name: string | null;
  payload: Record<string, unknown>;
  timestamp: string;
  duration_ms: number | null;
};

let token = localStorage.getItem('awp_token') ?? '';
export function setToken(next: string) {
  token = next;
  if (next) localStorage.setItem('awp_token', next);
  else localStorage.removeItem('awp_token');
}
export function getToken() {
  return token;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
      message?: string;
    } | null;
    throw new Error(body?.detail ?? body?.message ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
