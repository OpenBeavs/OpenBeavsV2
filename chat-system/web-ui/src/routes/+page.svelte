<script lang="ts">
  import { afterUpdate, getContext, tick } from 'svelte';
  import { guestChatsKey, type GuestChats } from '$lib/context';
  import Icon from '$lib/components/Icon.svelte';
  import MarkdownReply from '$lib/components/MarkdownReply.svelte';
  import Spinner from '$lib/components/Spinner.svelte';

  const { conversation, selected } = getContext<GuestChats>(guestChatsKey);
  let scrollArea: HTMLDivElement;
  let composer: HTMLFormElement;
  let input: HTMLTextAreaElement;
  let dockHeight: number;
  let composerWidth: number;
  let measuredDraft: string | undefined;
  let measuredWidth: number | undefined;
  let pulse: Animation | undefined;
  let atBottom = true;
  let previousChat: number | undefined;

  async function scrollToBottom() {
    await tick();
    if (atBottom && scrollArea) scrollArea.scrollTop = scrollArea.scrollHeight;
  }
  $: if ($conversation.messages.length || $conversation.pending) void scrollToBottom();
  $: if (dockHeight) void scrollToBottom();
  $: if ($selected !== previousChat) {
    previousChat = $selected;
    atBottom = true;
    void scrollToBottom();
  }

  function send() {
    if ($conversation.pending !== null || !$conversation.draft.trim()) return;
    atBottom = true;
    input.focus({ preventScroll: true });
    void conversation.send(window.location.hostname);
  }
  function handleKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault(); send();
    }
  }
  afterUpdate(() => {
    if (!input || (input.value === measuredDraft && composerWidth === measuredWidth)) return;
    measuredDraft = input.value;
    measuredWidth = composerWidth;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  });

  function pulseComposer() {
    pulse?.cancel();
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    pulse = composer.animate(
      [{ transform: 'scale(1)' }, { transform: 'scale(1.008)' }, { transform: 'scale(1)' }],
      { duration: 180, easing: 'ease-in-out' }
    );
  }
</script>

<div class="chat-page" style:--composer-dock-height={dockHeight ? `${dockHeight}px` : undefined}>
  <div class="chat-heading"><span class="accent"><Icon name="sparkles" size={25} /></span><h1>Chris</h1><span class="muted">OpenBeavs AI Hub</span><span class="badge">Guest</span></div>
  <div class="chat-scroll" bind:this={scrollArea} on:scroll={() => { atBottom = scrollArea.scrollHeight - scrollArea.scrollTop - scrollArea.clientHeight <= 8; }}>
    <div class="transcript" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
      {#if $conversation.messages.length === 0 && !$conversation.pending}
        <div class="empty-chat"><span class="accent"><Icon name="sparkles" size={44} /></span><h2>How can Chris help?</h2><p>Ask a question about OSU or anything on your mind.</p><p class="routing-note">Chris finds a specialist for your question or answers directly with Gemini.</p></div>
      {/if}
      {#each $conversation.messages as message (message.id)}
        <div class="message-row" class:user={message.role === 'user'}>
          <div class="message-wrapper">
            <div class="message-bubble" data-testid="message" aria-label={message.role === 'user' ? 'You' : 'Chris'}>
              {#if message.role === 'assistant'}
                <MarkdownReply content={message.content} />
              {:else}
                {message.content}
              {/if}
            </div>
            {#if message.role === 'assistant' && message.routing?.agent_name?.trim()}
              <p class="message-attribution muted">Answered by {message.routing.agent_name}</p>
            {/if}
          </div>
        </div>
      {/each}
      {#if $conversation.pending}
        <div class="message-row user"><div class="message-wrapper"><div class="message-bubble" aria-label="You">{$conversation.pending}</div></div></div>
        <div class="message-row"><div class="thinking" role="status"><Spinner /><span>Chris is thinking…</span></div></div>
      {/if}
    </div>
    <div class="composer-dock" bind:offsetHeight={dockHeight}>
      {#if $conversation.error}
        <div class="notice error">
          <p role="alert">{$conversation.error}</p>
          {#if $conversation.failedDraft !== null}
            <details class="failed-draft">
              <summary>View failed message</summary>
              <p>{$conversation.failedDraft}</p>
            </details>
          {/if}
        </div>
      {/if}
      <form class="composer" bind:this={composer} bind:clientWidth={composerWidth} on:submit|preventDefault={send} aria-label="Chat composer">
        <label class="sr-only" for="chat-input">Message Chris</label>
        <textarea id="chat-input" bind:this={input} rows="1" placeholder="Message Chris…" value={$conversation.draft} on:input={(event) => conversation.setDraft(event.currentTarget.value)} on:keydown={handleKey} on:click={pulseComposer}></textarea>
        <button class="send-button" type="submit" disabled={!$conversation.draft.trim() || $conversation.pending !== null} aria-label="Send message"><Icon name="send" size={29} /></button>
      </form>
      <p class="chat-footnote">Refreshing clears this tab’s chat list. Chris can make mistakes.</p>
    </div>
  </div>
</div>
