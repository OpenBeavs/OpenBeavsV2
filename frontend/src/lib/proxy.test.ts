import { once } from 'node:events';
import { createServer as createHttpServer, type Server } from 'node:http';
import { createServer, preview } from 'vite';
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

  const config = {
    server: { host, watch: null, hmr: false },
    preview: { host, port: 0 },
    logLevel: 'silent' as const
  };
  try {
    const server = mode === 'dev' ? await createServer(config) : await preview(config);
    try {
      if ('listen' in server) await server.listen();
      if (!server.httpServer) throw new Error('Expected Vite to start an HTTP server');
      const base = origin(server.httpServer);
      for (const [method, path] of [
        ['GET', '/health'], ['POST', '/chris/message'], ['GET', '/chris/agents']
      ]) {
        const response = await fetch(base + path, { method });
        expect(response.status).toBe(204);
      }

      // Use only the stub upstream so this regression test cannot delete data.
      const blocked = await fetch(base + '/chris/chats/expired', { method: 'DELETE' });
      await blocked.body?.cancel();
      expect(forwarded).toEqual(['GET /health', 'POST /chris/message', 'GET /chris/agents']);
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
