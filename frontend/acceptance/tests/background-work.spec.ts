import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

for (const enabled of [false, true]) {
  test(`analysis backlog ${enabled ? 'appears when enabled' : 'does not show a busy indicator when disabled'}`, async ({ page }) => {
    const readiness = page.getByTestId('readiness-panel');
    await page.addLocatorHandler(readiness, async () => {
      await readiness.getByRole('button', { name: 'Close', exact: true }).click();
    });
    const phase = (enabled: boolean, pending: number, completed: number) => ({
      enabled, pending, completed, processing: 0, failed: 0,
    });
    await page.route('**/api/processing/stats', route => route.fulfill({ json: {
      phase_stats: {
        metadata: phase(true, 0, 4266),
        clip: phase(enabled, 83, 4150),
        face_detection: phase(false, 874, 3359),
        vlm_caption: phase(false, 4233, 0),
      },
    } }));
    const stats = page.waitForResponse('**/api/processing/stats');
    await page.goto('/browse');
    await waitForShell(page);
    await stats;
    const indicator = page.locator('.processing-indicator');
    if (!enabled) {
      await expect(indicator).toHaveCount(0);
      return;
    }
    await expect(indicator).toBeVisible();
    await indicator.click();
    await expect(page.getByText('Visual Indexing', { exact: true })).toBeVisible();
    await expect(page.getByText('Face Analysis', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Visual Analysis', { exact: true })).toHaveCount(0);
  });
}
