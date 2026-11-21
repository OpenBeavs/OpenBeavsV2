import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

// This is a server-side proxy target, never a browser credential or API key.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'BACKEND_');
  const target = env.BACKEND_ORIGIN || 'http://127.0.0.1:8000';
  const proxy = {
    '^/chris(?:/|$)': { target, changeOrigin: true },
    '^/health$': { target, changeOrigin: true }
  };
  return {
    plugins: [sveltekit()],
    server: { proxy },
    preview: { proxy }
  };
});
