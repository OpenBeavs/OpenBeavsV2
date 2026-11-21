import { get, writable } from 'svelte/store';
import { sendMessage, type ChrisRequest, type ChrisResponse, type HistoryMessage } from './api';

export type ChatMessage = HistoryMessage & { id: string; routing?: ChrisResponse };
export type Conversation = {
  messages: ChatMessage[];
  draft: string;
  pending: string | null;
  error: string | null;
  chatId: string | null;
  guestId: string | null;
  storageUnavailable: boolean;
};

const empty = (): Conversation => ({
  messages: [], draft: '', pending: null, error: null,
  chatId: null, guestId: null, storageUnavailable: false
});

/** One in-memory conversation per app instance, shared by both routes.
 * Generation checks discard responses after reset even if cancellation is ignored.
 */
export function createConversation(
  transport: (request: ChrisRequest, signal: AbortSignal) => Promise<ChrisResponse> = sendMessage,
  id: () => string = () => crypto.randomUUID()
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
      const guestId = before.guestId ?? id();
      controller = new AbortController();
      // Timeout covers routing plus the direct-answer model call. Reset aborts locally only.
      const controllerForRequest = controller;
      const timer = setTimeout(() => controllerForRequest.abort(), 90_000);
      const request: ChrisRequest = {
        message,
        history: before.messages.map(({ role, content }) => ({ role, content })),
        guest_session_id: guestId,
        source_domain: sourceDomain,
        ...(before.chatId && !before.storageUnavailable ? { chat_id: before.chatId } : {})
      };
      state.set({ ...before, guestId, draft: '', pending: message, error: null });
      try {
        const reply = await transport(request, controller.signal);
        if (generation !== currentGeneration) return;
        const storageUnavailable = before.storageUnavailable || reply.chat_id === null;
        state.update((current) => ({
          ...current,
          messages: [...before.messages,
            { id: id(), role: 'user', content: message },
            { id: id(), role: 'assistant', content: reply.response, routing: reply }],
          pending: null,
          chatId: storageUnavailable ? null : reply.chat_id,
          storageUnavailable
        }));
      } catch (error) {
        if (generation !== currentGeneration) return;
        state.update((current) => ({
          ...current,
          pending: null,
          draft: before.draft,
          error: controllerForRequest.signal.aborted
            ? 'The request timed out. Chris may still finish on the server; retrying can duplicate a turn.'
            : error instanceof Error ? error.message : 'The request failed. Please try again.'
        }));
      } finally {
        clearTimeout(timer);
      }
    }
  };
}
