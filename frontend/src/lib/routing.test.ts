import { afterEach, describe, expect, it, vi } from 'vitest';
import { isRoutingInfo, sendMessage, type ChrisRequest, type RoutingInfo } from './api';

const selected: RoutingInfo = {
  status: 'selected',
  agent: { id: 'math', name: 'Math Expert', description: 'Arithmetic.' },
  confidence: 0.93,
  reason: 'Arithmetic question.'
};
const noMatch: RoutingInfo = { status: 'no_match', agent: null, confidence: 0.9, reason: 'A greeting.' };
const failure = {
  status: 'error',
  agent: null,
  confidence: null,
  reason: null,
  error: { code: 'registry_timeout', retryable: true, source: 'chris' }
};
const payload: ChrisRequest = { message: 'Hi', history: [], guest_session_id: 'g', source_domain: 'localhost' };
const reply = (routing: unknown) => ({
  response: 'The registry selected Math Expert.', chat_id: 'c', routed_to: null, agent_name: null,
  routing_confidence: null, routing_reason: null, routing
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('routing result validation', () => {
  it.each([selected, noMatch])('accepts a consistent %# result', (routing) => {
    expect(isRoutingInfo(routing)).toBe(true);
  });

  it.each([
    ['unknown status', { ...selected, status: 'maybe' }],
    ['selected without an agent', { ...selected, agent: null }],
    ['selected with an error', { ...selected, error: failure.error }],
    ['no_match with an agent', { ...noMatch, agent: selected.agent }],
    ['backend error payload', failure],
    ['error naming an agent', { ...failure, agent: selected.agent }],
    ['legacy error field', { ...selected, error: null }],
    ['confidence out of range', { ...selected, confidence: 4 }],
    ['confidence as text', { ...selected, confidence: '0.9' }],
    ['agent without a name', { ...selected, agent: { id: 'm' } }],
    ['not an object', 'selected']
  ])('rejects %s', (_name, routing) => {
    expect(isRoutingInfo(routing)).toBe(false);
  });

  it('keeps a valid routing result on the response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(reply(selected))));
    expect((await sendMessage(payload)).routing).toEqual(selected);
  });

  it('still accepts a plain reply with no routing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(reply(null))));
    expect((await sendMessage(payload)).routing).toBeNull();
  });

  it.each([{ ...selected, agent: null }, { ...failure, error: {} }, 'selected', { status: 'selected' }])(
    'rejects a response whose routing is malformed', async (routing) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(reply(routing))));
      await expect(sendMessage(payload)).rejects.toThrow('invalid response');
    });
});
