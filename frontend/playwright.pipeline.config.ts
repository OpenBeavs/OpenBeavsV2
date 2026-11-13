import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const localPython = resolve('../backend/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.PIPELINE_PYTHON || (existsSync(localPython) ? localPython : 'python');

// Browser tests against the REAL Chat + Chris + registry code with a FAKE (scripted)
// registry model: see ../backend/scripts/fake_model_stack.py. Local development mode only.
// Run: npm run test:pipeline   (PLAYWRIGHT_CHANNEL=msedge uses the installed Edge)
export default defineConfig({
  testDir: './tests',
  testMatch: /pipeline\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 45_000,
  use: {
    baseURL: 'http://127.0.0.1:5273',
    browserName: 'chromium',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: [
    {
      command: `"${python}" scripts/fake_model_stack.py`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8100/health',
      timeout: 90_000,
      reuseExistingServer: false
    },
    {
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5273 --strictPort',
      env: { BACKEND_ORIGIN: 'http://127.0.0.1:8100' },
      url: 'http://127.0.0.1:5273',
      timeout: 90_000,
      reuseExistingServer: false
    }
  ]
});
