import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkHealth, listAgents, sendMessage, type ChrisRequest } from './api';

const payload: ChrisRequest = { message: 'Hello', history: [], guest_session_id: 'guest-test', source_domain: 'localhost' };
const reply = { response: 'Hello!', chat_id: 'chat-test', routed_to: null, agent_name: null, routing_confidence: null, routing_reason: null };
afterEach(() => { vi.unstubAllGlobals(); });

function rejectOnAbort(signal: AbortSignal, reason: () => unknown): Promise<never> {
  return new Promise((_, reject) => {
    if (signal.aborted) reject(reason());
    else signal.addEventListener('abort', () => reject(reason()), { once: true });
  });
}

describe('v2 API contract', () => {
  it.each(['response headers', 'response body'])('times out a stalled agent list at %s with a caller signal', async (stage) => {
    const deadline = new AbortController();
    const caller = new AbortController();
    const timeout = vi.spyOn(AbortSignal, 'timeout').mockReturnValue(deadline.signal);
    const response = new Response();
    const readBody = vi.spyOn(response, 'json');
    const fetch = vi.fn(async (_path: string, { signal }: { signal: AbortSignal }) => {
      if (stage === 'response headers') return rejectOnAbort(signal, () => signal.reason);
      readBody.mockImplementation(() => rejectOnAbort(signal, () => new DOMException('Aborted', 'AbortError')));
      return response;
    });
    vi.stubGlobal('fetch', fetch);
    const result = listAgents(caller.signal);
    const rejection = expect(result).rejects.toMatchObject({ name: 'TimeoutError', message: expect.stringContaining('timed out') });
    expect(timeout).toHaveBeenCalledWith(90_000);
    expect(fetch.mock.calls[0][1].signal).not.toBe(caller.signal);
    if (stage === 'response body') await vi.waitFor(() => expect(readBody).toHaveBeenCalled());
    deadline.abort(new DOMException('Deadline exceeded', 'TimeoutError'));
    await rejection;
    expect(caller.signal.aborted).toBe(false);
  });

  it('preserves caller cancellation before the agent list deadline', async () => {
    const deadline = new AbortController();
    const caller = new AbortController();
    vi.spyOn(AbortSignal, 'timeout').mockReturnValue(deadline.signal);
    vi.stubGlobal('fetch', vi.fn((_path: string, { signal }: { signal: AbortSignal }) =>
      rejectOnAbort(signal, () => signal.reason)));
    const rejection = expect(listAgents(caller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    caller.abort();
    await rejection;
    expect(deadline.signal.aborted).toBe(false);
  });

  it('sends only the v2 payload without legacy auth or empty chat IDs', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(reply));
    vi.stubGlobal('fetch', fetch);
    expect(await sendMessage(payload)).toEqual(reply);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/chat/message');
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
    await expect(sendMessage(payload)).rejects.toThrow('Chris is temporarily unavailable');
  });

  it('checks health and validates the agent list', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ status: 'ok' }))
      .mockResolvedValueOnce(Response.json([])).mockResolvedValueOnce(Response.json([{}]));
    vi.stubGlobal('fetch', fetch);
    await checkHealth();
    expect(await listAgents()).toEqual([]);
    await expect(listAgents()).rejects.toThrow('invalid agent list');
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/health', '/chat/agents', '/chat/agents']);
  });
});
