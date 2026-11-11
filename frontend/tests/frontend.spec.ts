import { test, expect, type Page } from '@playwright/test';

const response = { response: 'Hello from Chris', chat_id: 'chat-browser', routed_to: null, agent_name: null, routing_confidence: null, routing_reason: null };
const agents = [
  { id: 'library', name: 'Library', description: 'Find research resources', endpoint_url: 'https://example.com/a2a', card_url: null, trust_tier: 'public', required_role: null, skills: [], capabilities: {}, is_featured: true },
  { id: 'advising', name: 'Advising', description: 'Degree planning', endpoint_url: 'https://example.com/private', card_url: null, trust_tier: 'privileged', required_role: 'student', skills: null, capabilities: null, is_featured: false }
];

async function mockBackend(page: Page) {
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/chat/agents', (route) => route.fulfill({ json: agents }));
  await page.route('**/chat/message', (route) => route.fulfill({ json: response }));
}
async function send(page: Page, text: string) {
  await page.getByLabel('Message Chris', { exact: true }).fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
}

test.beforeEach(async ({ page }) => { await mockBackend(page); });

test('talks to Chris, carries the chat ID, and preserves the conversation across navigation', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 430 });
  const requests: Record<string, unknown>[] = [];
  page.on('request', (request) => { if (request.url().endsWith('/chat/message')) requests.push(request.postDataJSON()); });
  await page.goto('/');
  await send(page, 'Hello');
  await expect(page.getByRole('textbox', { name: 'Message Chris' })).toBeFocused();
  await expect(page.getByTestId('message')).toHaveCount(2);
  await page.getByRole('link', { name: 'Agents', exact: true }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  await page.getByRole('link', { name: 'Chris', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveCount(2);
  await send(page, 'Remember that?');
  await expect(page.getByTestId('message')).toHaveCount(4);
  await expect.poll(async () => {
    const reply = await page.getByTestId('message').last().boundingBox();
    const bar = await page.getByRole('form', { name: 'Chat composer' }).boundingBox();
    return !!reply && !!bar && reply.y + reply.height <= bar.y;
  }).toBe(true);
  expect(requests[0]).not.toHaveProperty('chat_id');
  expect(requests[1]).toMatchObject({ chat_id: 'chat-browser', guest_session_id: requests[0].guest_session_id, history: [
    { role: 'user', content: 'Hello' }, { role: 'assistant', content: response.response }
  ] });
  const composer = page.getByRole('textbox', { name: 'Message Chris' });
  await composer.fill('Unsent first-chat draft');
  await page.getByRole('button', { name: 'New Chat', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveCount(0);
  await expect(composer).toHaveValue('');
  await send(page, 'Fresh');
  await expect(page.getByTestId('message')).toHaveCount(2);
  expect(requests[2]).not.toHaveProperty('chat_id');
  expect(requests[2].guest_session_id).not.toBe(requests[0].guest_session_id);

  await page.getByRole('button', { name: 'Pin Hello', exact: true }).click();
  const pinned = page.getByRole('region', { name: 'Pinned' });
  await pinned.getByRole('button', { name: 'Hello', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveText(['Hello', response.response, 'Remember that?', response.response]);
  await expect(composer).toHaveValue('Unsent first-chat draft');
  await page.getByRole('button', { name: 'Fresh', exact: true }).click();
  await expect(page.getByTestId('message')).toHaveText(['Fresh', response.response]);
  await pinned.getByRole('button', { name: 'Unpin Hello' }).press('Enter');
  await expect(page.getByRole('region', { name: 'Recent' }).getByRole('button', { name: 'Hello', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('message')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Hello', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Fresh', exact: true })).toHaveCount(0);
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
  await page.route('**/chat/message', (route) => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
  await page.goto('/'); await send(page, 'Keep this input');
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable');
  await expect(page.getByLabel('Message Chris', { exact: true })).toHaveValue('Keep this input');
  await expect(page.getByTestId('message')).toHaveCount(0);
  await page.route('**/chat/message', async (route) => {
    expect(route.request().postDataJSON().history).toEqual([]);
    await route.fulfill({ json: response });
  });
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByTestId('message')).toHaveCount(2);
});

test('supports keyboard input and safely renders Markdown in Chris replies', async ({ page }) => {
  const html = '<img src=x onerror=alert(1)><script>alert(1)</script>';
  const markdown = [
    '**Bold reply** and *emphasis*.',
    '[Safe link](https://example.com) and [Unsafe link](javascript:void(0)).',
    '![Image alt text](https://example.com/image.png)',
    html
  ].join('\n\n');
  await page.route('**/chat/message', (route) => route.fulfill({ json: { ...response, response: markdown } }));
  await page.goto('/');
  const input = page.getByLabel('Message Chris', { exact: true });
  await input.fill('**First line**'); await input.press('Shift+Enter'); await input.press('a');
  await expect(input).toHaveValue('**First line**\na');
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true });
  await expect(page.getByTestId('message')).toHaveCount(0);
  await input.press('Enter');
  const guest = page.getByTestId('message').first();
  const reply = page.getByTestId('message').last();
  await expect(guest).toContainText('**First line**');
  await expect(guest.locator('strong')).toHaveCount(0);
  await expect(reply.locator('strong')).toHaveText('Bold reply');
  await expect(reply.locator('em')).toHaveText('emphasis');
  await expect(reply.getByRole('link', { name: 'Safe link', exact: true })).toHaveAttribute('href', /^https:\/\/example\.com\/?$/);
  await expect(reply.getByRole('link')).toHaveCount(1);
  await expect(reply).toContainText('Image alt text');
  await expect(reply).toContainText(html);
  await expect(reply.locator('img, script')).toHaveCount(0);
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
  await page.route('**/chat/message', (route) => route.fulfill({ json: { ...response, chat_id: null, routed_to: 'library', agent_name: 'Library' } }));
  await page.goto('/'); await send(page, 'Find research');
  await expect(page.getByText('Routing preview · Library')).toBeVisible();
  await expect(page.getByText(/Conversation storage is unavailable/)).toBeVisible();
});

test('offers a retry when the agent list stalls', async ({ page }) => {
  await page.addInitScript(() => {
    AbortSignal.timeout = () => {
      const deadline = new AbortController();
      window.addEventListener('test-deadline', () => {
        deadline.abort(new DOMException('Deadline exceeded', 'TimeoutError'));
      }, { once: true });
      return deadline.signal;
    };
  });
  await page.route('**/chat/agents', () => {}, { times: 1 });
  const requested = page.waitForRequest('**/chat/agents');
  await page.goto('/agents');
  await requested;
  await expect(page.getByText('Loading agents…')).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('test-deadline')));
  await expect(page.getByRole('alert')).toContainText('timed out');
  await page.getByRole('button', { name: 'Retry loading agents' }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
});

test('retries agent-list failures independently and handles an empty list', async ({ page }) => {
  await page.route('**/chat/agents', (route) => route.fulfill({ status: 500, json: {} }));
  await page.goto('/agents');
  await expect(page.getByRole('alert')).toBeVisible();
  await page.route('**/chat/agents', (route) => route.fulfill({ json: [] }));
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
  expect(apiPaths.sort()).toEqual(['/chat/agents', '/chat/message', '/health']);
});
