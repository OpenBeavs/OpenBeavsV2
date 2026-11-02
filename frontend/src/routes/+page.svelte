<script lang="ts">
  import { getContext, tick } from 'svelte';
  import { conversationKey, type ConversationStore } from '$lib/context';
  import Icon from '$lib/components/Icon.svelte';
  import Spinner from '$lib/components/Spinner.svelte';

  const conversation = getContext<ConversationStore>(conversationKey);
  let transcript: HTMLDivElement;
  let input: HTMLTextAreaElement;
  let atBottom = true;

  async function scrollToBottom() {
    await tick();
    if (atBottom && transcript) transcript.scrollTop = transcript.scrollHeight;
  }
  $: if ($conversation.messages.length || $conversation.pending) void scrollToBottom();

  function send() {
    atBottom = true;
    void conversation.send(window.location.hostname);
  }
  function handleKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault(); send();
    }
  }
  function resize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }
</script>

<div class="chat-page">
  <div class="chat-heading"><span class="accent"><Icon name="sparkles" size={25} /></span><h1>Chris</h1><span class="muted">OpenBeavs AI Hub</span><span class="badge">Guest</span></div>
  <div class="transcript" bind:this={transcript} role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions" on:scroll={() => { atBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80; }}>
    {#if $conversation.messages.length === 0 && !$conversation.pending}
      <div class="empty-chat"><span class="accent"><Icon name="sparkles" size={44} /></span><h2>How can Chris help?</h2><p>Ask a question about OSU or anything on your mind.</p><p class="routing-note">Chris can answer directly and preview which registered agent fits your question. Agent calls are coming later.</p></div>
    {/if}
    {#each $conversation.messages as message (message.id)}
      <div class="message-row" class:user={message.role === 'user'}>
        <div class="message-wrapper">
          {#if message.role === 'assistant' && message.routing?.routed_to}
            <span class="badge routing-badge" title={message.routing.routing_reason ?? undefined}>Routing preview · {message.routing.agent_name ?? message.routing.routed_to}</span>
          {/if}
          <div class="message-bubble" data-testid="message" aria-label={message.role === 'user' ? 'You' : 'Chris'}>{message.content}</div>
        </div>
      </div>
    {/each}
    {#if $conversation.pending}
      <div class="message-row user"><div class="message-wrapper"><div class="message-bubble" aria-label="You">{$conversation.pending}</div></div></div>
      <div class="message-row"><div class="thinking" role="status"><Spinner /><span>Chris is thinking…</span></div></div>
    {/if}
  </div>
  {#if $conversation.error}<div class="notice error" role="alert">{$conversation.error}</div>{/if}
  {#if $conversation.storageUnavailable}<div class="notice" role="status">Conversation storage is unavailable. You can continue here until you refresh.</div>{/if}
  <form class="composer" on:submit|preventDefault={send} aria-label="Chat composer">
    <label class="sr-only" for="chat-input">Message Chris</label>
    <textarea id="chat-input" bind:this={input} rows="1" placeholder="Message Chris…" value={$conversation.draft} disabled={$conversation.pending !== null} on:input={(event) => { conversation.setDraft(event.currentTarget.value); resize(); }} on:keydown={handleKey}></textarea>
    <button class="send-button" type="submit" disabled={!$conversation.draft.trim() || $conversation.pending !== null} aria-label="Send message"><Icon name="send" size={29} /></button>
  </form>
  <p class="chat-footnote">Refreshing or starting a new chat clears this view, not records already stored by the backend. Chris can make mistakes.</p>
</div>
