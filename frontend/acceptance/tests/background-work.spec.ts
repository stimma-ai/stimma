import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

for (const enabled of [false, true]) {
  test(`analysis backlog ${enabled ? 'appears when enabled' : 'does not show a busy indicator when disabled'}`, async ({ page }) => {
    const readiness = page.getByTestId('readiness-panel');
    const phase = (enabled: boolean, pending: number, completed: number) => ({
      enabled, pending, completed, processing: 0, failed: 0,
    });
    await page.route('**/api/processing/stats', route => route.fulfill({ json: {
      phase_stats: {
        metadata: phase(true, 0, 4266),
        clip: phase(enabled, 83, 4150),
        face_detection: phase(false, 874, 3359),
      },
    } }));
    const stats = page.waitForResponse('**/api/processing/stats');
    await page.goto('/browse');
    await waitForShell(page);
    // Initial onboarding handles readiness itself. Register the late-dialog
    // handler afterward so it cannot remove the button that helper is clicking.
    await page.addLocatorHandler(readiness, async () => {
      await readiness.getByRole('button', { name: 'Close', exact: true }).click();
    });
    await stats;
    const indicator = page.locator('.processing-indicator');
    if (!enabled) {
      await expect(indicator).toHaveCount(0);
      return;
    }
    await expect(indicator).toBeVisible();
    await indicator.click();
    await expect(page.getByText('Visual indexing', { exact: true })).toBeVisible();
    await expect(page.getByText('Face analysis', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Visual analysis', { exact: true })).toHaveCount(0);
  });
}

test('browse ignores retired filters and opens criteria without keyword requests', async ({ page }, testInfo) => {
  const keywordRequests: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/keywords/')) keywordRequests.push(request.url());
  });
  const counts = page.waitForResponse(response => response.url().includes('/assets/filter-counts'));
  await page.goto('/browse?cq=old-caption&k=animal&xk=indoor');
  await waitForShell(page);
  const filters = page.getByRole('button', { name: 'Filters', exact: true });
  if (await filters.getAttribute('aria-expanded') !== 'true') await filters.click();
  const response = await counts;
  if (await filters.getAttribute('aria-expanded') !== 'true') await filters.click();
  await expect(page.getByRole('heading', { name: 'AI search', exact: true })).toBeVisible();
  expect(response.ok()).toBeTruthy();
  expect(response.url()).not.toMatch(/[?&](caption_query|keywords|excluded_keywords|keyword_limit)=/);
  expect(await response.json()).not.toHaveProperty('keywords');
  await expect(page.getByRole('heading', { name: 'Keywords', exact: true })).toHaveCount(0);
  expect(keywordRequests).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('browse-without-keywords.png'), animations: 'disabled' });
});
