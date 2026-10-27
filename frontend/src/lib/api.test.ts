import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkHealth, listAgents, sendMessage, type ChrisRequest } from './api';

const payload: ChrisRequest = { message: 'Hello', history: [], guest_session_id: 'guest-test', source_domain: 'localhost' };
const reply = { response: 'Hello!', chat_id: 'chat-test', routed_to: null, agent_name: null, routing_confidence: null, routing_reason: null };
afterEach(() => { vi.unstubAllGlobals(); });

describe('v2 API contract', () => {
  it('sends only the v2 payload without legacy auth or empty chat IDs', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(reply));
    vi.stubGlobal('fetch', fetch);
    expect(await sendMessage(payload)).toEqual(reply);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/chris/message');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
    expect(init.body).not.toContain('user_id');
    expect(init.body).not.toContain('chat_id');
  });

  it.each([400, 403, 422, 500, 503, 502])('handles HTTP %s without echoing the response body', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private server details', { status })));
    await expect(sendMessage(payload)).rejects.toMatchObject({ status });
    await expect(sendMessage(payload)).rejects.not.toThrow('private server details');
  });

  it.each([{}, { ...reply, chat_id: 7 }, { ...reply, response: '' }, { ...reply, routed_to: [] }])('rejects malformed message responses', async (data) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(data)));
    await expect(sendMessage(payload)).rejects.toThrow('invalid response');
  });

  it('handles non-JSON and network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>proxy error</html>')));
    await expect(sendMessage(payload)).rejects.toThrow('invalid response');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network failed')));
    await expect(sendMessage(payload)).rejects.toThrow('Could not reach Chris');
  });

  it('checks health and validates the agent list', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ status: 'ok' }))
      .mockResolvedValueOnce(Response.json([])).mockResolvedValueOnce(Response.json([{}]));
    vi.stubGlobal('fetch', fetch);
    await checkHealth();
    expect(await listAgents()).toEqual([]);
    await expect(listAgents()).rejects.toThrow('invalid agent list');
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/health', '/chris/agents', '/chris/agents']);
  });
});
