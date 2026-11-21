import { describe, expect, it } from 'vitest';
import { availableToGuest, filterAgents } from './agents';
import type { AgentSummary } from './api';

const agent: AgentSummary = { id: 'library', name: 'Library', description: 'Research resources', endpoint_url: 'https://example.com/agent', card_url: null, trust_tier: 'public', required_role: null, skills: null, capabilities: null, is_featured: true };
describe('directory', () => {
  it('matches names and descriptions case-insensitively', () => {
    expect(filterAgents([agent], ' LIBRARY ')).toEqual([agent]);
    expect(filterAgents([agent], 'RESEARCH')).toEqual([agent]);
    expect(filterAgents([agent], 'missing')).toEqual([]);
  });
  it('marks restricted and unknown tiers or role requirements unavailable', () => {
    expect(availableToGuest(agent)).toBe(true);
    for (const trust_tier of ['authenticated', 'privileged', 'unknown']) expect(availableToGuest({ ...agent, trust_tier })).toBe(false);
    expect(availableToGuest({ ...agent, required_role: 'student' })).toBe(false);
  });
});
