import type { AgentSummary } from './api';

/** Match the router's guest eligibility without pretending to authorize execution. */
export function availableToGuest(agent: AgentSummary): boolean {
  return agent.trust_tier === 'public' && agent.required_role === null;
}

export function filterAgents(agents: AgentSummary[], query: string): AgentSummary[] {
  const term = query.trim().toLowerCase();
  return agents.filter((agent) => `${agent.name} ${agent.description ?? ''}`.toLowerCase().includes(term));
}
