<script lang="ts">
  import type { RoutingInfo } from '$lib/api';
  import { confidenceLabel, describeError, headline } from '$lib/routing';

  export let routing: RoutingInfo;
  $: confidence = confidenceLabel(routing.confidence);
</script>

<!-- A routing decision from the registry, not an answer: no expert has been called. -->
<div class="routing-card {routing.status}" data-testid="message" data-status={routing.status}
  aria-label="Chris">
  <div class="routing-head">
    <span class="routing-pill" data-testid="routing-pill">
      {routing.status === 'selected' ? 'Selected' : routing.status === 'no_match' ? 'No match' : 'Error'}
    </span>
    <strong data-testid="routing-headline">{headline(routing)}</strong>
  </div>

  {#if routing.status === 'selected' && routing.agent}
    {#if routing.agent.description}<p class="routing-line" data-testid="routing-description">{routing.agent.description}</p>{/if}
    <dl class="routing-facts">
      <dt>Expert id</dt><dd data-testid="routing-agent-id">{routing.agent.id}</dd>
      {#if confidence}<dt>Confidence</dt><dd data-testid="routing-confidence">{confidence}</dd>{/if}
      {#if routing.reason}<dt>Why</dt><dd data-testid="routing-reason">{routing.reason}</dd>{/if}
    </dl>
    <p class="routing-caveat">Selection only. This expert has not been called, so this is not its answer.</p>
  {:else if routing.status === 'no_match'}
    <p class="routing-line">The registry found no registered expert that fits this question.</p>
    {#if routing.reason}<p class="routing-line" data-testid="routing-reason">Why: {routing.reason}</p>{/if}
    <p class="routing-caveat">No expert was called and nothing was answered.</p>
  {:else if routing.error}
    <p class="routing-line" data-testid="routing-error-text">{describeError(routing.error.code)}</p>
    <dl class="routing-facts">
      <dt>Code</dt><dd data-testid="routing-error-code">{routing.error.code}</dd>
      <dt>Reported by</dt><dd data-testid="routing-error-source">{routing.error.source === 'registry' ? 'the registry' : 'Chris (could not get a usable registry reply)'}</dd>
      <dt>Retry</dt><dd>{routing.error.retryable ? 'Trying again may help.' : 'Trying again will not help until this is fixed.'}</dd>
    </dl>
  {/if}
</div>

<style>
  .routing-card { max-width: min(560px, 100%); border: 1px solid var(--border); border-left-width: 4px;
    border-radius: 12px; padding: 12px 15px; background: var(--subtle); font-size: 13px; line-height: 1.6; }
  .routing-card.selected { border-left-color: #16a34a; }
  .routing-card.no_match { border-left-color: #ca8a04; }
  .routing-card.error { border-left-color: #dc2626; }
  .routing-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .routing-pill { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; padding: 2px 8px;
    border-radius: 999px; border: 1px solid var(--border); color: var(--muted); background: var(--surface); }
  .routing-line { margin: 6px 0 0; }
  .routing-facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 8px 0 0; font-size: 12px; }
  .routing-facts dt { color: var(--muted); }
  .routing-facts dd { margin: 0; overflow-wrap: anywhere; }
  .routing-caveat { margin: 8px 0 0; font-size: 11px; color: var(--muted); }
</style>
