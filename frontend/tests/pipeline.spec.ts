import { test, expect, type Page } from '@playwright/test';

// Real Chat + Chris + registry, with a scripted (fake) registry model. See
// backend/scripts/fake_model_stack.py for which words trigger which behavior.
// No expert is ever called; a selection is shown as a selection, never as an answer.

async function ask(page: Page, text: string) {
  await page.getByLabel('Message Chris', { exact: true }).fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
}
const lastCard = (page: Page) => page.locator('[data-status]').last();
// Evidence for humans: screenshots of each outcome in test-results/screenshots/.
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-results/screenshots/${name}.png`, fullPage: true });

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Check backend connection' })).toContainText('Backend connected');
});

test('labels the demonstration as local development mode', async ({ page }) => {
  const banner = page.getByTestId('local-dev-banner');
  await expect(banner).toContainText('Local development mode');
  await expect(banner).toContainText('does not verify production authentication');
  await expect(banner).toContainText('No expert is called');
});

test('shows the selected expert, not raw JSON and not an answer', async ({ page }) => {
  await ask(page, 'What is 15 percent of 240? (math)');
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'selected');
  await expect(card.getByTestId('routing-headline')).toHaveText('Expert selected: Math Expert');
  await expect(card.getByTestId('routing-agent-id')).toHaveText('math-expert');
  // The registry sends only the id and endpoint: no confidence or reason is shown.
  await expect(card.getByTestId('routing-confidence')).toHaveCount(0);
  await expect(card.getByTestId('routing-reason')).toHaveCount(0);
  await expect(card).toContainText('Arithmetic, percentages');
  await expect(card).toContainText('not its answer');
  await shot(page, '1-selected');
  const text = await page.locator('body').innerText();
  expect(text).not.toContain('openbeavs.registry.select');
  expect(text).not.toContain('"status"');
  expect(text).not.toContain('example.test'); // expert endpoints stay server-side
});

test('selects the OSU expert for an OSU question', async ({ page }) => {
  await ask(page, 'Tell me about OSU housing');
  await expect(lastCard(page).getByTestId('routing-headline')).toHaveText('Expert selected: OSU Expert');
});

test('shows no match for a greeting and for a weak guess', async ({ page }) => {
  await ask(page, 'hello there');
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'no_match');
  await expect(card.getByTestId('routing-headline')).toHaveText('No matching expert');
  await expect(card).toContainText('nothing was answered');
  await shot(page, '2-no-match');

  await ask(page, 'weak match please');
  await expect(page.locator('[data-status="no_match"]')).toHaveCount(2);
});

test('earlier turns reach the registry', async ({ page }) => {
  // With history the follow-up is matched to the OSU expert; without it there is no match.
  await ask(page, 'Tell me about OSU housing');
  await expect(page.locator('[data-status="selected"]')).toHaveCount(1);
  await ask(page, 'followup please');
  await expect(page.locator('[data-status="selected"]')).toHaveCount(2);
  await expect(lastCard(page).getByTestId('routing-headline')).toHaveText('Expert selected: OSU Expert');

  await page.getByRole('button', { name: 'New Chat', exact: true }).click();
  await ask(page, 'followup please');
  await expect(page.locator('[data-status="no_match"]')).toHaveCount(1);
});

test('shows a registry-reported error with its code and source', async ({ page }) => {
  await ask(page, 'please break');
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'error');
  await expect(card.getByTestId('routing-error-code')).toHaveText('selection_unavailable');
  await expect(card.getByTestId('routing-error-source')).toHaveText('the registry');
  await expect(card).toContainText('Trying again may help');
  await shot(page, '3-registry-error');
});

test('shows an unusable model reply as an error, not as a selection', async ({ page }) => {
  await ask(page, 'garbage in');
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'error');
  await expect(card.getByTestId('routing-error-code')).toHaveText('invalid_model_reply');
});

test('shows a slow registry as a timeout reported by Chris', async ({ page }) => {
  await ask(page, 'this is slow');
  await expect(page.getByText('Chris is thinking…')).toBeVisible();
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'error', { timeout: 15_000 });
  await expect(card.getByTestId('routing-error-code')).toHaveText('registry_timeout');
  await expect(card.getByTestId('routing-error-source')).toContainText('Chris');
  await shot(page, '4-timeout');
});

test('an expert revoked during selection is not shown as selected', async ({ page }) => {
  await ask(page, 'please revoke');
  const card = lastCard(page);
  await expect(card).toHaveAttribute('data-status', 'error');
  await expect(card.getByTestId('routing-error-code')).toHaveText('agent_unavailable');
  await shot(page, '5-revoked-during-selection');
  await expect(page.getByText('Expert selected: Flaky Expert')).toHaveCount(0);
  // The harness restores the expert shortly afterwards; the pipeline keeps working.
  await page.waitForTimeout(2000);
  await ask(page, 'Tell me about OSU admissions');
  await expect(page.locator('[data-status="selected"]')).toHaveCount(1);
});

test('every outcome keeps the conversation usable', async ({ page }) => {
  await ask(page, 'hello');
  await expect(page.locator('[data-status]')).toHaveCount(1);
  await ask(page, 'something with math');
  await expect(page.locator('[data-status]')).toHaveCount(2);
  await ask(page, 'break it');
  await expect(page.locator('[data-status]')).toHaveCount(3);
  await expect(page.getByTestId('message')).toHaveCount(6);
});
