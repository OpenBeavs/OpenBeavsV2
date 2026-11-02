import { test, expect, type Page } from '@playwright/test';

const response = { response: 'Hello from Chris', chat_id: 'chat-browser', routed_to: null, agent_name: null, routing_confidence: null, routing_reason: null };
const agents = [
  { id: 'library', name: 'Library', description: 'Find research resources', endpoint_url: 'https://example.com/a2a', card_url: null, trust_tier: 'public', required_role: null, skills: [], capabilities: {}, is_featured: true },
  { id: 'advising', name: 'Advising', description: 'Degree planning', endpoint_url: 'https://example.com/private', card_url: null, trust_tier: 'privileged', required_role: 'student', skills: null, capabilities: null, is_featured: false }
];

async function mockBackend(page: Page) {
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/chris/agents', (route) => route.fulfill({ json: agents }));
  await page.route('**/chris/message', (route) => route.fulfill({ json: response }));
}
async function send(page: Page, text: string) {
  await page.getByLabel('Message Chris', { exact: true }).fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
}

test.beforeEach(async ({ page }) => { await mockBackend(page); });

test('talks to Chris, carries the chat ID, and preserves the conversation across navigation', async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  page.on('request', (request) => { if (request.url().endsWith('/chris/message')) requests.push(request.postDataJSON()); });
  await page.goto('/');
  await send(page, 'Hello');
  await expect(page.getByTestId('message')).toHaveCount(2);
  await page.getByRole('link', { name: 'Agents', exact: true }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  await page.getByRole('link', { name: 'Chris', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveCount(2);
  await send(page, 'Remember that?');
  await expect(page.getByTestId('message')).toHaveCount(4);
  expect(requests[0]).not.toHaveProperty('chat_id');
  expect(requests[1]).toMatchObject({ chat_id: 'chat-browser', guest_session_id: requests[0].guest_session_id, history: [
    { role: 'user', content: 'Hello' }, { role: 'assistant', content: response.response }
  ] });
  await page.getByRole('button', { name: 'New Chat', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveCount(0);
  await send(page, 'Fresh');
  await expect(page.getByTestId('message')).toHaveCount(2);
  expect(requests[2]).not.toHaveProperty('chat_id');
  expect(requests[2].guest_session_id).not.toBe(requests[0].guest_session_id);
  await page.reload();
  await expect(page.getByTestId('message')).toHaveCount(0);
});

test('searches the read-only directory and labels restricted agents', async ({ page }) => {
  await page.goto('/agents');
  await expect(page.getByRole('article', { name: 'Advising' })).toContainText('Unavailable in this guest version');
  await page.getByLabel('Search agents').fill('RESEARCH');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByRole('article', { name: 'Library' })).toContainText('Featured');
  await page.getByLabel('Search agents').fill('nothing');
  await expect(page.getByText('No agents match your search.')).toBeVisible();
});

test('restores failed input and recovers without adding failed turns', async ({ page }) => {
  await page.route('**/chris/message', (route) => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
  await page.goto('/'); await send(page, 'Keep this input');
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable');
  await expect(page.getByLabel('Message Chris', { exact: true })).toHaveValue('Keep this input');
  await expect(page.getByTestId('message')).toHaveCount(0);
  await page.route('**/chris/message', async (route) => {
    expect(route.request().postDataJSON().history).toEqual([]);
    await route.fulfill({ json: response });
  });
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByTestId('message')).toHaveCount(2);
});

test('supports keyboard input and escapes HTML-like message content', async ({ page }) => {
  const html = '<img src=x onerror=alert(1)><script>alert(1)</script>';
  await page.route('**/chris/message', (route) => route.fulfill({ json: { ...response, response: html } }));
  await page.goto('/');
  const input = page.getByLabel('Message Chris', { exact: true });
  await input.fill('First line'); await input.press('Shift+Enter'); await input.press('a');
  await expect(input).toHaveValue('First line\na');
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true });
  await expect(page.getByTestId('message')).toHaveCount(0);
  await input.press('Enter');
  await expect(page.getByTestId('message').last()).toHaveText(html);
  await expect(page.getByTestId('message').locator('img, script')).toHaveCount(0);
});

test('opens, traps focus, and closes the mobile sidebar with Escape', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/');
  await page.getByRole('button', { name: 'Toggle sidebar' }).click();
  await expect(page.getByRole('dialog', { name: 'Sidebar' })).toBeVisible();
  await page.getByRole('button', { name: /Use .* theme/ }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Collapse sidebar' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Toggle sidebar' })).toBeFocused();
  await expect(page.getByRole('button', { name: 'Toggle sidebar' })).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('shows routing previews and persistence fallback without direct agent calls', async ({ page }) => {
  await page.route('**/chris/message', (route) => route.fulfill({ json: { ...response, chat_id: null, routed_to: 'library', agent_name: 'Library' } }));
  await page.goto('/'); await send(page, 'Find research');
  await expect(page.getByText('Routing preview · Library')).toBeVisible();
  await expect(page.getByText(/Conversation storage is unavailable/)).toBeVisible();
});

test('retries agent-list failures independently and handles an empty list', async ({ page }) => {
  await page.route('**/chris/agents', (route) => route.fulfill({ status: 500, json: {} }));
  await page.goto('/agents');
  await expect(page.getByRole('alert')).toBeVisible();
  await page.route('**/chris/agents', (route) => route.fulfill({ json: [] }));
  await page.getByRole('button', { name: 'Retry loading agents' }).click();
  await expect(page.getByText(/No agents are registered yet/)).toBeVisible();
  await page.getByRole('link', { name: 'Chris', exact: true }).click();
  await send(page, 'Hello'); await expect(page.getByTestId('message')).toHaveCount(2);
});

test('calls only supported backend endpoints and never restores legacy auth', async ({ page }) => {
  const apiPaths: string[] = [];
  page.on('request', (request) => {
    if (['fetch', 'xhr', 'websocket'].includes(request.resourceType())) {
      const path = new URL(request.url()).pathname;
      if (!path.includes('__data.json')) apiPaths.push(path);
      expect(request.headers()).not.toHaveProperty('authorization');
    }
  });
  await page.goto('/'); await send(page, 'Hello');
  await expect(page.getByTestId('message')).toHaveCount(2);
  await page.getByRole('link', { name: 'Agents', exact: true }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  expect(apiPaths.sort()).toEqual(['/chris/agents', '/chris/message', '/health']);
});
