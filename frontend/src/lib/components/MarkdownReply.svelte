<script context="module" lang="ts">
  import MarkdownIt from 'markdown-it';

  // Replies are untrusted. Render Markdown without raw HTML or embedded resources.
  const markdown = new MarkdownIt({ html: false, breaks: true });
  markdown.validateLink = (url) => /^https?:\/\//i.test(url) && URL.canParse(url);
  markdown.renderer.rules.image = (tokens, index, options, env, renderer) =>
    markdown.utils.escapeHtml(renderer.renderInlineAsText(tokens[index].children ?? [], options, env));
</script>

<script lang="ts">
  export let content: string;
  $: html = markdown.render(content);
</script>

<div class="markdown-reply">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- Only render output from the restricted Markdown parser. -->
  {@html html}
</div>
