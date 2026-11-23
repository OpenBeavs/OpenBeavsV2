import type { createGuestChats } from './guest-chats';

export const guestChatsKey = Symbol('guestChats');
export type GuestChats = ReturnType<typeof createGuestChats>;
