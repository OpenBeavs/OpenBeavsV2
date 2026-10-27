<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { page } from '$app/stores';
  import Icon from './Icon.svelte';

  export let open = false;
  export let dark = false;
  export let onNewChat: () => void;
  export let onToggleTheme: () => void;
  let mobile = true;
  let drawer: HTMLElement;

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
    <button class="new-chat" on:click={() => { onNewChat(); if (mobile) close(); }}>
      <img src="/favicon.png" alt="" width="23" height="23" />
      <span>New Chat</span><Icon name="new" size={18} />
    </button>
  </div>
  <nav aria-label="Main navigation">
    <a href="/" class:active={$page.url.pathname === '/'} aria-current={$page.url.pathname === '/' ? 'page' : undefined} on:click={() => { if (mobile) close(); }}><Icon name="sparkles" size={19} />Chris</a>
    <a href="/agents" class:active={$page.url.pathname === '/agents'} aria-current={$page.url.pathname === '/agents' ? 'page' : undefined} on:click={() => { if (mobile) close(); }}><Icon name="agents" size={19} />Agents</a>
  </nav>
  <div class="sidebar-note">Your conversation stays here while you browse. Refreshing starts a new chat.</div>
  <div class="sidebar-footer">
    <div class="guest-avatar" aria-hidden="true">G</div>
    <div class="guest-label"><strong>Guest</strong><span>OpenBeavs AI Hub</span></div>
    <button class="icon-button" aria-label={dark ? 'Use light theme' : 'Use dark theme'} on:click={onToggleTheme}><Icon name={dark ? 'sun' : 'moon'} size={19} /></button>
  </div>
</aside>
