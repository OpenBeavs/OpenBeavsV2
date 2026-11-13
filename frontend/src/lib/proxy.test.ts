import { once } from 'node:events';
import { createServer as createHttpServer, type Server } from 'node:http';
import { createServer, loadConfigFromFile, preview } from 'vite';
import { afterEach, expect, it, vi } from 'vitest';

const host = '127.0.0.1';

function origin(server: Pick<Server, 'address'>): string {
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Expected a listening HTTP server');
  return `http://${host}:${address.port}`;
}

afterEach(() => { vi.unstubAllEnvs(); });

it.each(['dev', 'preview'])('only forwards the UI routes in %s', async (mode) => {
  const forwarded: string[] = [];
  const upstream = createHttpServer((request, response) => {
    forwarded.push(`${request.method} ${request.url}`);
    response.writeHead(204).end();
  });
  upstream.listen(0, host);
  await once(upstream, 'listening');
  vi.stubEnv('BACKEND_ORIGIN', origin(upstream));

  try {
    const isPreview = mode === 'preview';
    const viteMode = isPreview ? 'production' : 'development';
    const loaded = await loadConfigFromFile({ command: 'serve', mode: viteMode, isPreview });
    const proxy = isPreview ? loaded?.config.preview?.proxy : loaded?.config.server?.proxy;
    if (!proxy) throw new Error(`Expected proxy rules in vite.config.ts for ${mode}`);

    // Exercise Vite's proxy without running SvelteKit's build-dependent preview hook.
    const config = { configFile: false as const, mode: viteMode, logLevel: 'silent' as const };
    const server = isPreview
      ? await preview({ ...config, preview: { host, port: 0, proxy } })
      : await createServer({ ...config, server: { host, watch: null, hmr: false, proxy } });
    try {
      if ('listen' in server) await server.listen();
      if (!server.httpServer) throw new Error('Expected Vite to start an HTTP server');
      const base = origin(server.httpServer);
      for (const [method, path] of [
        ['GET', '/health'], ['POST', '/chat/message'], ['GET', '/chat/agents']
      ]) {
        const response = await fetch(base + path, { method });
        expect(response.status).toBe(204);
      }

      // Use only the stub upstream so this regression test cannot delete data.
      const blocked = await fetch(base + '/chat/chats/expired', { method: 'DELETE' });
      await blocked.body?.cancel();
      expect(forwarded).toEqual(['GET /health', 'POST /chat/message', 'GET /chat/agents']);
    } finally {
      await server.close();
    }
  } finally {
    await new Promise<void>((resolve, reject) => {
      upstream.close((error) => error ? reject(error) : resolve());
      upstream.closeAllConnections();
    });
  }
}, 15_000);
