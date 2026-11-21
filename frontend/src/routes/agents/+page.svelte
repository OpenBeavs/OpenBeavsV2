<script lang="ts">
  import { onMount } from 'svelte';
  import { listAgents, type AgentSummary } from '$lib/api';
  import { availableToGuest, filterAgents } from '$lib/agents';
  import Icon from '$lib/components/Icon.svelte';
  import Spinner from '$lib/components/Spinner.svelte';

  let agents: AgentSummary[] = [];
  let loading = true;
  let error = '';
  let query = '';
  let controller: AbortController;
  $: filtered = filterAgents(agents, query);

  async function load() {
    controller?.abort();
    controller = new AbortController();
    loading = true; error = '';
    try { agents = await listAgents(controller.signal); }
    catch (failure) { if (!controller.signal.aborted) error = failure instanceof Error ? failure.message : 'Could not load agents.'; }
    finally { loading = false; }
  }
  onMount(() => { void load(); return () => controller?.abort(); });
  const tierLabel = (tier: string) => ({ public: 'Public', authenticated: 'Authentication required', privileged: 'Privileged access required' }[tier] ?? `Access tier: ${tier}`);
</script>

<svelte:head><title>Agents · OpenBeavs</title></svelte:head>
<section class="agents-page" aria-labelledby="agents-heading">
  <div class="section-heading"><div><h1 id="agents-heading">Agents</h1><p class="muted">Explore the agents registered with OpenBeavs.</p></div><span class="directory-icon"><Icon name="agents" size={28} /></span></div>
  <p class="notice">Chris currently previews routing to public agents. Direct agent calls and OSU sign-in are not available yet.</p>
  <label class="sr-only" for="agent-search">Search agents</label>
  <input id="agent-search" class="search-input" type="search" placeholder="Search agents by name or description…" bind:value={query} />
  {#if loading}
    <div class="directory-state" role="status"><Spinner />Loading agents…</div>
  {:else if error}
    <div class="notice error" role="alert">{error}<button class="text-button" on:click={load}>Retry loading agents</button></div>
  {:else if agents.length === 0}
    <div class="directory-state">No agents are registered yet. You can still talk to Chris.</div>
  {:else if filtered.length === 0}
    <div class="directory-state">No agents match your search.</div>
  {:else}
    <p class="result-count" role="status">{filtered.length} {filtered.length === 1 ? 'agent' : 'agents'}</p>
    <div class="agent-grid">
      {#each filtered as agent (agent.id)}
        <article class="agent-card" aria-label={agent.name}>
          <div class="agent-card-top"><span class="agent-avatar"><Icon name="agents" size={24} /></span>{#if agent.is_featured}<span class="badge featured">Featured</span>{/if}</div>
          <h2>{agent.name}</h2><p>{agent.description || 'No description provided.'}</p>
          <div class="agent-tags"><span class="badge">{tierLabel(agent.trust_tier)}</span>{#if agent.required_role}<span class="badge">Role: {agent.required_role}</span>{/if}</div>
          <div class="agent-availability" class:restricted={!availableToGuest(agent)}>{availableToGuest(agent) ? 'Available for routing preview' : 'Unavailable in this guest version'}</div>
        </article>
      {/each}
    </div>
  {/if}
</section>
