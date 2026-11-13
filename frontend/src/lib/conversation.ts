import { get, writable } from 'svelte/store';
import { sendMessage, type ChrisRequest, type ChrisResponse, type HistoryMessage } from './api';

export type ChatMessage = HistoryMessage & { id: string; routing?: ChrisResponse };
export type Conversation = {
  messages: ChatMessage[];
  draft: string;
  pending: string | null;
  error: string | null;
  failedDraft: string | null;
};

const empty = (): Conversation => ({
  messages: [], draft: '', pending: null, error: null, failedDraft: null
});

/** Keep message IDs cryptographically random even on plain HTTP dev origins. */
function createId(): string {
  const crypto = globalThis.crypto;
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

/** One in-memory conversation with its own request and transcript.
 * Generation checks discard responses after reset even if cancellation is ignored.
 */
export function createConversation(
  transport: (request: ChrisRequest, signal: AbortSignal) => Promise<ChrisResponse> = sendMessage,
  id: () => string = createId
) {
  const state = writable<Conversation>(empty());
  let generation = 0;
  let controller: AbortController | undefined;

  return {
    subscribe: state.subscribe,
    setDraft(draft: string) { state.update((current) => ({ ...current, draft })); },
    reset() {
      generation += 1;
      controller?.abort();
      state.set(empty());
    },
    async send(sourceDomain: string) {
      const before = get(state);
      const message = before.draft.trim();
      if (!message || before.pending !== null) return;
      const currentGeneration = generation;
      let userMessageId: string;
      let assistantMessageId: string;
      try {
        userMessageId = id();
        assistantMessageId = id();
      } catch {
        state.update((current) => ({
          ...current,
          error: 'Could not prepare the message. Please try again in a browser with cryptography support.'
        }));
        return;
      }
      controller = new AbortController();
      // Timeout covers routing plus the direct-answer model call. Reset aborts locally only.
      const controllerForRequest = controller;
      const timer = setTimeout(() => controllerForRequest.abort(), 90_000);
      const request: ChrisRequest = {
        message,
        history: before.messages.map(({ role, content }) => ({ role, content })),
        source_domain: sourceDomain,
      };
      state.set({ ...before, draft: '', pending: message, error: null, failedDraft: null });
      try {
        const reply = await transport(request, controller.signal);
        if (generation !== currentGeneration) return;
        state.update((current) => ({
          ...current,
          messages: [...before.messages,
            { id: userMessageId, role: 'user', content: message },
            { id: assistantMessageId, role: 'assistant', content: reply.response, routing: reply }],
          pending: null,
        }));
      } catch (error) {
        if (generation !== currentGeneration) return;
        state.update((current) => ({
          ...current,
          pending: null,
          // The textarea stays editable while this request is in flight.
          draft: current.draft || before.draft,
          failedDraft: current.draft ? before.draft : null,
          error: controllerForRequest.signal.aborted || (error instanceof Error && error.name === 'TimeoutError')
            ? 'The request timed out. Chris may still finish on the server; please try again.'
            : error instanceof Error ? error.message : 'The request failed. Please try again.'
        }));
      } finally {
        clearTimeout(timer);
      }
    }
  };
}
