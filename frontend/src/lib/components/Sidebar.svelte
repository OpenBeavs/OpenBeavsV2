<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/stores';
  import type { GuestChatSummary } from '../guest-chats';
  import Icon from './Icon.svelte';

  export let open = false;
  export let dark = false;
  export let chats: GuestChatSummary[];
  export let selected: number;
  export let onNewChat: () => void;
  export let onSelectChat: (id: number) => void;
  export let onTogglePin: (id: number) => void;
  export let onToggleTheme: () => void;
  let mobile = true;
  let drawer: HTMLElement;
  $: groups = [
    { name: 'Pinned', chats: chats.filter((chat) => chat.pinned) },
    { name: 'Recent', chats: chats.filter((chat) => !chat.pinned) }
  ];

  onMount(() => {
    const media = window.matchMedia('(min-width: 768px)');
    const update = () => { mobile = !media.matches; open = media.matches; };
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  });

  function close() {
    open = false;
    void tick().then(() => document.getElementById('sidebar-toggle')?.focus());
  }

  function togglePin(id: number, button: HTMLButtonElement) {
    const hadFocus = document.activeElement === button;
    onTogglePin(id);
    // Moving between groups replaces the row, so restore keyboard focus there.
    if (hadFocus) void tick().then(() => drawer.querySelector<HTMLButtonElement>(`[data-chat-pin="${id}"]`)?.focus());
  }

  // Keep keyboard focus within the mobile drawer and return it to its trigger.
  $: if (open && mobile && drawer) {
    void tick().then(() => drawer.querySelector<HTMLButtonElement>('button')?.focus());
  }

  function handleKey(event: KeyboardEvent) {
    if (!open || !mobile) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key !== 'Tab') return;
    const elements = drawer.querySelectorAll<HTMLElement>('button, a[href]');
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
</script>

<svelte:window on:keydown={handleKey} />

{#if open && mobile}
  <button class="drawer-backdrop" aria-label="Close sidebar" tabindex="-1" on:click={close}></button>
{/if}
<aside bind:this={drawer} id="sidebar" class:open role={mobile ? 'dialog' : undefined} aria-modal={mobile && open ? 'true' : undefined} aria-label="Sidebar" aria-hidden={!open} inert={!open}>
  <div class="sidebar-top">
    <button class="icon-button" aria-label="Collapse sidebar" on:click={close}><Icon name="menu" /></button>
    <button class="new-chat" on:click={() => { if (mobile) open = false; onNewChat(); }}>
      <img src="/favicon.png" alt="" width="23" height="23" />
      <span>New Chat</span><Icon name="new" size={18} />
    </button>
  </div>
  <nav aria-label="Main navigation">
    <a href="/" class:active={$page.url.pathname === '/'} aria-current={$page.url.pathname === '/' ? 'page' : undefined} on:click={() => { if (mobile) close(); }}><Icon name="sparkles" size={19} />Chris</a>
    <a href="/agents" class:active={$page.url.pathname === '/agents'} aria-current={$page.url.pathname === '/agents' ? 'page' : undefined} on:click={() => { if (mobile) close(); }}><Icon name="agents" size={19} />Agents</a>
  </nav>
  <div class="sidebar-chats">
    {#each groups as group (group.name)}
      {#if group.chats.length}
        <section aria-label={group.name}>
          <h2>{group.name}</h2>
          <ul>
            {#each group.chats as chat (chat.id)}
              {@const active = chat.id === selected && $page.url.pathname === '/'}
              <li class:active>
                <button class="chat-select" aria-current={active ? 'true' : undefined} title={chat.title}
                  on:click={() => { if (mobile) open = false; onSelectChat(chat.id); }}>{chat.title}</button>
                <button class="icon-button chat-pin" class:pinned={chat.pinned} data-chat-pin={chat.id}
                  aria-label={`${chat.pinned ? 'Unpin' : 'Pin'} ${chat.title}`}
                  title={chat.pinned ? 'Unpin chat' : 'Pin chat'}
                  on:click={(event) => togglePin(chat.id, event.currentTarget)}><Icon name="pin" size={16} /></button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/each}
  </div>
  <p class="sidebar-note">Chats and pins last until you refresh or close this tab.</p>
  <div class="sidebar-footer">
    <div class="guest-avatar" aria-hidden="true">G</div>
    <div class="guest-label"><strong>Guest</strong><span>OpenBeavs AI Hub</span></div>
    <button class="icon-button" aria-label={dark ? 'Use light theme' : 'Use dark theme'} on:click={onToggleTheme}><Icon name={dark ? 'sun' : 'moon'} size={19} /></button>
  </div>
</aside>
