import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createConversation } from './conversation';
import type { ChrisResponse } from './api';

const reply = (chat_id: string | null = 'chat-1'): ChrisResponse => ({
  response: 'Hello!', chat_id, routed_to: null, agent_name: null, routing_confidence: null, routing_reason: null
});
const idFactory = () => { let value = 0; return () => `id-${++value}`; };

afterEach(() => { vi.unstubAllGlobals(); });

describe('in-memory conversation', () => {
  it('uses secure UUIDs when randomUUID is unavailable on plain HTTP', async () => {
    const crypto = globalThis.crypto;
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const transport = vi.fn().mockResolvedValue(reply());
    const chat = createConversation(transport);
    const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

    chat.setDraft('Hello'); await chat.send('dev.example');
    chat.setDraft('Follow-up'); await chat.send('dev.example');
    expect(transport.mock.calls[1][0]).not.toHaveProperty("guest_session_id");
    const ids = get(chat).messages.map(({ id }) => id);
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
    ids.forEach((id) => expect(id).toMatch(uuidV4));

    chat.reset();
    chat.setDraft('Fresh'); await chat.send('dev.example');
    expect(get(chat).messages).toHaveLength(2);
  });

  it('keeps the draft and never sends if a message ID cannot be generated', async () => {
    const transport = vi.fn().mockResolvedValue(reply());
    const id = vi.fn((): string => { throw new Error('Crypto unavailable'); }).mockReturnValueOnce('guest');
    const chat = createConversation(transport, id);
    chat.setDraft('Keep this');
    await chat.send('localhost');
    expect(transport).not.toHaveBeenCalled();
    expect(get(chat)).toMatchObject({ draft: 'Keep this', pending: null, messages: [],
      error: expect.stringContaining('Could not prepare the message') });
  });

  it('preserves the draft and reports failure when the API times out', async () => {
    const transport = vi.fn().mockRejectedValue(new DOMException('Deadline exceeded', 'TimeoutError'));
    const chat = createConversation(transport, idFactory());
    chat.setDraft('Keep this');
    await chat.send('localhost');
    expect(get(chat)).toMatchObject({ draft: 'Keep this', pending: null, messages: [],
      error: expect.stringContaining('please try again') });
  });

  it('sends earlier successful turns without guest or chat IDs', async () => {
    const transport = vi.fn().mockResolvedValue(reply());
    const chat = createConversation(transport, idFactory());
    chat.setDraft(' Hello '); await chat.send('localhost');
    expect(transport.mock.calls[0][0]).not.toHaveProperty('chat_id');
    chat.setDraft('Follow-up'); await chat.send('localhost');
    expect(transport.mock.calls[1][0]).toMatchObject({ history: [
      { role: 'user', content: 'Hello' }, { role: 'assistant', content: 'Hello!' }
    ] });
    expect(get(chat).messages).toHaveLength(4);
  });

  it('restores failed input and excludes errors and failed turns from history', async () => {
    const transport = vi.fn().mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValue(reply());
    const chat = createConversation(transport, idFactory());
    chat.setDraft('Try this'); await chat.send('localhost');
    expect(get(chat)).toMatchObject({ draft: 'Try this', error: 'Unavailable', messages: [], pending: null });
    await chat.send('localhost');
    expect(transport.mock.calls[1][0].history).toEqual([]);
    expect(get(chat).error).toBeNull();
  });

  it('ignores empty input and duplicate sends while pending', async () => {
    let resolve!: (value: ChrisResponse) => void;
    const transport = vi.fn(() => new Promise<ChrisResponse>((done) => { resolve = done; }));
    const chat = createConversation(transport, idFactory());
    await chat.send('localhost');
    expect(transport).not.toHaveBeenCalled();
    chat.setDraft('Hello'); const pending = chat.send('localhost');
    await chat.send('localhost');
    expect(transport).toHaveBeenCalledTimes(1);
    resolve(reply()); await pending;
  });

  it('resets identities and discards late responses even when transport ignores abort', async () => {
    let resolve!: (value: ChrisResponse) => void;
    const transport = vi.fn().mockImplementationOnce(() => new Promise<ChrisResponse>((done) => { resolve = done; }))
      .mockResolvedValue(reply('chat-2'));
    const chat = createConversation(transport, idFactory());
    chat.setDraft('Old chat'); const pending = chat.send('localhost');
    chat.reset();
    expect(transport.mock.calls[0][1].aborted).toBe(true);
    chat.setDraft('New chat'); await chat.send('localhost');
    resolve(reply('old-chat')); await pending;
    expect(get(chat).messages[0].content).toBe('New chat');
    expect(transport.mock.calls[1][0].history).toEqual([]);
  });

  it('ignores legacy returned chat IDs and always sends browser history', async () => {
    const transport = vi.fn().mockResolvedValueOnce(reply()).mockResolvedValueOnce(reply(null)).mockResolvedValue(reply('new-fragment'));
    const chat = createConversation(transport, idFactory());
    for (const text of ['one', 'two', 'three', 'four']) { chat.setDraft(text); await chat.send('localhost'); }
    expect(transport.mock.calls[1][0]).not.toHaveProperty('chat_id');
    expect(transport.mock.calls[2][0]).not.toHaveProperty('chat_id');
    expect(transport.mock.calls[3][0]).not.toHaveProperty('chat_id');
    expect(transport.mock.calls[3][0].history).toHaveLength(6);
    expect(transport.mock.calls[3][0]).not.toHaveProperty("guest_session_id");
  });

  it('gives each app instance fresh state and does not store transcripts in browser storage', async () => {
    const first = createConversation(vi.fn().mockResolvedValue(reply()), idFactory());
    first.setDraft('Hello'); await first.send('localhost');
    const second = createConversation();
    expect(get(first).messages).toHaveLength(2);
    expect(get(second)).toMatchObject({ messages: [] });
  });
});
