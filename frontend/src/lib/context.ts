import type { createConversation } from './conversation';

export const conversationKey = Symbol('conversation');
export type ConversationStore = ReturnType<typeof createConversation>;
