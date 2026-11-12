/** The small browser-facing contract implemented by the v2 Chris router. */
export type HistoryMessage = { role: 'user' | 'assistant'; content: string };

export type ChrisRequest = {
  message: string;
  history: HistoryMessage[];
  guest_session_id: string;
  source_domain: string;
  chat_id?: string;
};

/** Chris's routing decision. A selection is a decision only: no expert has been called. */
export type RoutingInfo = {
  status: 'selected' | 'no_match';
  agent: { id: string; name: string; description: string | null } | null;
  confidence: number | null;
  reason: string | null;
};

export type ChrisResponse = {
  response: string;
  chat_id: string | null;
  routed_to: string | null;
  agent_name: string | null;
  routing_confidence: number | null;
  routing_reason: string | null;
  /** Structured routing result; absent or null for plain replies. */
  routing?: RoutingInfo | null;
};

export type AgentSummary = {
  id: string;
  name: string;
  description: string | null;
  endpoint_url: string;
  card_url: string | null;
  trust_tier: string;
  required_role: string | null;
  skills: unknown[] | null;
  capabilities: Record<string, unknown> | null;
  is_featured: boolean;
};

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

/** True only for a routing result that is complete and consistent with its status. */
export function isRoutingInfo(value: unknown): value is RoutingInfo {
  if (!isRecord(value)) return false;
  const { status, agent, confidence, reason } = value;
  if ('error' in value) return false;
  if (status !== 'selected' && status !== 'no_match') return false;
  if (!(confidence === null || (typeof confidence === 'number' && Number.isFinite(confidence) && confidence >= 0 && confidence <= 1))) return false;
  if (!nullableString(reason)) return false;
  const validAgent = isRecord(agent) && typeof agent.id === 'string' && typeof agent.name === 'string' &&
    nullableString(agent.description);
  return status === 'selected' ? validAgent : agent === null;
}

/** Use fixed errors rather than echoing arbitrary server bodies into the UI/logs. */
async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, signal: init?.signal ?? AbortSignal.timeout(90_000) });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError('Chris is temporarily unavailable. Please try again shortly.');
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      400: 'Enter a non-empty message.',
      403: 'Access to this conversation was denied. Start a new chat to continue.',
      422: 'The backend could not accept this message. Please start a new chat and try again.',
      500: 'Chris is temporarily unavailable. Please try again shortly.',
      503: 'Chris is temporarily unavailable. Please try again shortly.'
    };
    throw new ApiError(messages[response.status] ?? 'The request failed. Please try again.', response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new ApiError('The backend returned an invalid response. Please try again.');
  }
}

/** Ordinary JSON request; v2 currently does not stream or verify bearer tokens. */
export async function sendMessage(payload: ChrisRequest, signal?: AbortSignal): Promise<ChrisResponse> {
  const data = await request('/chat/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal
  });
  if (!isRecord(data) || typeof data.response !== 'string' || !data.response.trim() ||
      !nullableString(data.chat_id) || !nullableString(data.routed_to) ||
      !nullableString(data.agent_name) || !nullableString(data.routing_reason) ||
      !(data.routing_confidence === null ||
        (typeof data.routing_confidence === 'number' && Number.isFinite(data.routing_confidence))) ||
      !(data.routing === undefined || data.routing === null || isRoutingInfo(data.routing))) {
    throw new ApiError('The backend returned an invalid response. Please try again.');
  }
  return data as ChrisResponse;
}

/** Agent URLs are metadata only; the browser never executes an external agent. */
export async function listAgents(signal?: AbortSignal): Promise<AgentSummary[]> {
  const data = await request('/chat/agents', { signal });
  if (!Array.isArray(data) || !data.every((agent: unknown) => isRecord(agent) &&
      typeof agent.id === 'string' && typeof agent.name === 'string' &&
      nullableString(agent.description) && typeof agent.endpoint_url === 'string' &&
      nullableString(agent.card_url) && typeof agent.trust_tier === 'string' &&
      nullableString(agent.required_role) && (agent.skills === null || Array.isArray(agent.skills)) &&
      (agent.capabilities === null || isRecord(agent.capabilities)) && typeof agent.is_featured === 'boolean')) {
    throw new ApiError('The backend returned an invalid agent list. Please try again.');
  }
  return data as AgentSummary[];
}

export async function checkHealth(): Promise<void> {
  const data = await request('/health');
  if (!isRecord(data) || data.status !== 'ok') throw new ApiError('The backend is not ready.');
}
