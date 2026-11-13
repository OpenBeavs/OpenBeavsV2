<script lang="ts">
  import { onMount, setContext, tick } from 'svelte';
  import { goto } from '$app/navigation';
  import { createGuestChats } from '$lib/guest-chats';
  import { guestChatsKey } from '$lib/context';
  import { checkHealth } from '$lib/api';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import '../app.css';

  const chats = createGuestChats();
  const { summaries, selected } = chats;
  setContext(guestChatsKey, chats);
  let sidebarOpen = false;
  let dark = false;
  let status: 'checking' | 'connected' | 'offline' = 'checking';
  let healthError = '';

  async function refreshHealth() {
    status = 'checking';
    try { await checkHealth(); status = 'connected'; healthError = ''; }
    catch (error) { status = 'offline'; healthError = error instanceof Error ? error.message : 'Backend unavailable.'; }
  }

  function applyTheme(value: boolean) {
    dark = value;
    document.documentElement.classList.toggle('dark', dark);
  }

  function toggleTheme() {
    applyTheme(!dark);
    try { localStorage.setItem('openbeavs-theme', dark ? 'dark' : 'light'); } catch { /* Optional preference storage. */ }
  }

  onMount(() => {
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    let preference: string | null = null;
    try { preference = localStorage.getItem('openbeavs-theme'); } catch { /* Use the system theme. */ }
    applyTheme(preference === 'dark' || (preference !== 'light' && system.matches));
    const followSystem = () => {
      try { if (localStorage.getItem('openbeavs-theme')) return; } catch { /* Follow system. */ }
      applyTheme(system.matches);
    };
    system.addEventListener('change', followSystem);
    void refreshHealth();
    return () => { system.removeEventListener('change', followSystem); chats.dispose(); };
  });

  async function showChat() {
    if (window.location.pathname !== '/') await goto('/');
    await tick();
    document.getElementById('chat-input')?.focus();
  }
</script>

<svelte:head><title>OpenBeavs · Chris</title><meta name="description" content="Talk to Chris, the OpenBeavs AI hub, and explore registered agents." /></svelte:head>

<a class="skip-link" href="#main">Skip to content</a>
<div class="app-shell">
  <Sidebar bind:open={sidebarOpen} {dark} chats={$summaries} selected={$selected}
    onNewChat={() => { chats.newChat(); void showChat(); }}
    onSelectChat={(id) => { chats.select(id); void showChat(); }}
    onTogglePin={chats.togglePin} onToggleTheme={toggleTheme} />
  <div class="main-shell" class:sidebar-open={sidebarOpen}>
    <header class="topbar">
      <div class="topbar-brand">
        <button id="sidebar-toggle" class="icon-button" aria-label="Toggle sidebar" aria-controls="sidebar" aria-expanded={sidebarOpen} on:click={() => sidebarOpen = !sidebarOpen}><Icon name="menu" /></button>
        <a href="/" class="brand">OpenBeavs</a><span class="version-label">AI Hub</span>
      </div>
      <button class="connection" class:offline={status === 'offline'} on:click={refreshHealth} disabled={status === 'checking'} title={healthError || 'Check backend connection. This does not check the model or database.'} aria-label="Check backend connection"><span class="status-dot"></span>{status === 'checking' ? 'Connecting…' : status === 'connected' ? 'Backend connected' : 'Backend offline · Retry'}</button>
    </header>
    <main id="main" tabindex="-1"><slot /></main>
  </div>
</div>
