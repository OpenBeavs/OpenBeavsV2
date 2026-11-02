<script lang="ts">
  // Small icons adapted from the original WebUI's standalone SVG components.
  export let name: 'sparkles' | 'menu' | 'send' | 'new' | 'agents' | 'sun' | 'moon';
  export let size = 20;
  const paths = {
    sparkles: 'M9 3l2.3 6.7L18 12l-6.7 2.3L9 21l-2.3-6.7L0 12l6.7-2.3L9 3zm10-2 1.2 3.8L24 6l-3.8 1.2L19 11l-1.2-3.8L14 6l3.8-1.2L19 1z',
    menu: 'M4 6h16M4 12h16M4 18h10',
    send: 'm8 11 4-4 4 4m-4-4v10M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
    new: 'm16 3 5 5M4 20l4-1L21 6l-3-3L5 16l-1 4Z',
    agents: 'M9 4h6v4H9zM5 12h14v9H5zM12 8v4M2 16h3m14 0h3M9 16h.01M15 16h.01',
    sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
    moon: 'M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z'
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name]} />
</svg>
