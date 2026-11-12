import { test, expect, type Page } from '@playwright/test';

// Real Chat, Chris and registry with a scripted registry model. Selection-only
// mode exercises failures without calling Gemini; no expert is called yet.
async function ask(page: Page, text: string) {
  const pending = page.waitForResponse(r => r.url().endsWith('/chat/message') && r.request().method() === 'POST');
  await page.getByLabel('Message Chris', { exact: true }).fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  return pending;
}
const lastReply = (page: Page) => page.locator('.message-bubble[aria-label="Chris"]').last();

async function unavailable(page: Page, question: string) {
  const response = await ask(page, question);
  expect(response.status()).toBe(503);
  expect(await response.json()).toEqual({ detail: 'Chris is temporarily unavailable. Please try again shortly.' });
  await expect(page.getByRole('alert')).toContainText('Chris is temporarily unavailable');
  await expect(page.getByTestId('message')).toHaveCount(0);
  await expect(page.locator('[data-status]')).toHaveCount(0);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Check backend connection' })).toContainText('Backend connected');
});

test('reports a selection as a normal message without debug details', async ({ page }) => {
  const response = await ask(page, 'What is 15 percent of 240? (math)');
  expect(response.status()).toBe(200);
  await expect(lastReply(page)).toHaveText('I found the Math Expert specialist for your question.');
  await expect(page.getByTestId('message')).toHaveCount(2);
  const text = await page.locator('body').innerText();
  for (const detail of ['math-expert', 'Confidence', 'Selection only.', 'example.test']) expect(text).not.toContain(detail);
  await expect(page.locator('[data-status]')).toHaveCount(0);
});

test('selects the OSU expert', async ({ page }) => {
  await ask(page, 'Tell me about OSU housing');
  await expect(lastReply(page)).toHaveText('I found the OSU Expert specialist for your question.');
});

test('reports diagnostic no-match as plain text', async ({ page }) => {
  await ask(page, 'hello there');
  await expect(lastReply(page)).toContainText('no registered expert');
  await ask(page, 'weak match please');
  await expect(page.getByTestId('message')).toHaveCount(4);
});

test('uses earlier successful turns for a follow-up', async ({ page }) => {
  await ask(page, 'Tell me about OSU housing');
  await expect(lastReply(page)).toContainText('OSU Expert');
  await ask(page, 'followup please');
  await expect(lastReply(page)).toContainText('OSU Expert');
  await page.getByRole('button', { name: 'New Chat', exact: true }).click();
  await ask(page, 'followup please');
  await expect(lastReply(page)).toContainText('no registered expert');
});

test('keeps registry errors out of messages and browser payloads', async ({ page }) => {
  await unavailable(page, 'please break');
});

test('does not turn an unusable model reply into a message', async ({ page }) => {
  await unavailable(page, 'garbage in');
});

test('handles registry timeout without saving a failed reply', async ({ page }) => {
  await unavailable(page, 'this is slow');
});

test('does not present a revoked expert as selected', async ({ page }) => {
  await unavailable(page, 'please revoke');
  await page.waitForTimeout(2000);
  await ask(page, 'Tell me about OSU admissions');
  await expect(lastReply(page)).toContainText('OSU Expert');
});

test('keeps failed turns out of follow-up history and recovers', async ({ page }) => {
  await ask(page, 'something with math');
  await expect(page.getByTestId('message')).toHaveCount(2);
  const failed = await ask(page, 'break it');
  expect(failed.status()).toBe(503);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('message')).toHaveCount(2);
  const recovered = await ask(page, 'Tell me about OSU housing');
  const sent = recovered.request().postDataJSON();
  expect(sent.history).toHaveLength(2);
  expect(JSON.stringify(sent.history)).not.toContain('break it');
  expect(JSON.stringify(sent.history)).not.toContain('unavailable');
  await expect(page.getByTestId('message')).toHaveCount(4);
});
