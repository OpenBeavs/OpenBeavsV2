import { derived, get, writable } from 'svelte/store';
import { createConversation, type Conversation } from './conversation';

export type GuestChatSummary = { id: number; title: string; pinned: boolean };

type GuestChat = {
  id: number;
  title: string | null;
  pinned: boolean;
  activity: number;
  store: ReturnType<typeof createConversation>;
};

/** Keep one independent conversation store per chat for the lifetime of the layout. */
export function createGuestChats() {
  const chats = new Map<number, GuestChat>();
  const summaries = writable<GuestChatSummary[]>([]);
  let nextId = 0;
  let activity = 0;

  function publish() {
    summaries.set([...chats.values()].sort((a, b) => b.activity - a.activity)
      .map(({ id, title, pinned }) => ({ id, title: title ?? 'Untitled chat', pinned })));
  }

  function add() {
    const chat = { id: ++nextId, title: null, pinned: false, activity: ++activity, store: createConversation() };
    chats.set(chat.id, chat);
    publish();
    return chat;
  }

  const active = writable<GuestChat>(add());
  const selected = derived(active, (chat) => chat.id);
  const conversation = derived<typeof active, Conversation>(active, (chat, set) => chat.store.subscribe(set));

  return {
    summaries: { subscribe: summaries.subscribe },
    selected,
    conversation: {
      subscribe: conversation.subscribe,
      setDraft(draft: string) { get(active).store.setDraft(draft); },
      async send(sourceDomain: string) {
        // Capture the chat before awaiting. The user may switch while it replies.
        const chat = get(active);
        const before = get(chat.store);
        if (before.pending !== null || !before.draft.trim()) return;
        const sending = chat.store.send(sourceDomain);
        if (get(chat.store).pending === null) return sending;
        const title = before.draft.trim().replace(/\s+/g, ' ');
        chat.title ??= title.length > 48 ? `${title.slice(0, 47)}…` : title;
        chat.activity = ++activity;
        publish();
        await sending;
        if (chats.has(chat.id) && get(chat.store).messages.length > before.messages.length) {
          chat.activity = ++activity;
          publish();
        }
      }
    },
    newChat() {
      const current = get(active);
      if (!current.pinned && current.title === null && get(current.store).draft === '') {
        current.store.reset();
        return;
      }
      active.set(add());
    },
    select(id: number) {
      const chat = chats.get(id);
      if (chat && chat !== get(active)) active.set(chat);
    },
    togglePin(id: number) {
      const chat = chats.get(id);
      if (!chat) return;
      chat.pinned = !chat.pinned;
      publish();
    },
    dispose() {
      for (const chat of chats.values()) chat.store.reset();
      chats.clear();
    }
  };
}
