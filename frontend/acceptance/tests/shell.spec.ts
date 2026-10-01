import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

test.describe('app shell acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('primary sidebar destinations are reachable', async ({ page }) => {
    page.on('pageerror', error => console.error('Shell runtime error:', error.message));
    page.on('console', message => { if (message.type() === 'error') console.error('Shell console:', message.text()); });
    const destinations = [
      { path: '/browse', text: 'Assets' },
      { path: '/tools', text: 'All Tools' },
      { path: '/boards', text: 'Boards' },
      { path: '/chats', text: 'Chats' },
      { path: '/flows', text: 'Flows' },
      { path: '/trash', text: 'Trash' },
    ];

    for (const destination of destinations) {
      await page.goto(destination.path);
      await waitForShell(page);
      await expect(page.getByText(destination.text, { exact: true }).first()).toBeVisible({ timeout: 30000 });
    }
  });

  test('browser back and forward work across core routes', async ({ page }) => {
    await page.goto('/tools');
    await expect(page.getByText('All Tools', { exact: true })).toBeVisible({ timeout: 30000 });

    await page.goto('/projects');
    await expect(page.getByRole('dialog', { name: 'Choose working context' })).toBeVisible({ timeout: 30000 });

    await page.goBack();
    await expect(page.getByText('All Tools', { exact: true })).toBeVisible({ timeout: 30000 });

    await page.goForward();
    await expect(page.getByRole('dialog', { name: 'Choose working context' })).toBeVisible({ timeout: 30000 });
  });
});
