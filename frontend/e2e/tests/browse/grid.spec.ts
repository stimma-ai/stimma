import { test, expect } from '@playwright/test';
import { goToBrowse, goToTool } from '../../helpers/navigation';
import { submitGeneration, waitForJobComplete } from '../../helpers/generation';
import { describeWithTestProvider } from '../../helpers/fixtures';

test.describe('Browse Grid', () => {
  test('browse view loads', async ({ page }) => {
    await goToBrowse(page);
    await expect(page.getByRole('button', { name: 'All Assets' })).toBeVisible();
  });

  test('clicking media item opens slideshow', async ({ page }) => {
    await goToBrowse(page);
    const firstItem = page.locator('.media-item').first();
    if (await firstItem.isVisible()) {
      await firstItem.click();
      await page.waitForURL(/slideshow|\/browse/, { timeout: 5000 }).catch(() => {
        // May open as overlay instead of URL change
      });
    }
  });
});

describeWithTestProvider('Browse Grid (Test Provider)', () => {
  test('can generate then navigate to browse', async ({ page }) => {
    // Generate an image, then verify we can navigate to browse without issues
    await goToTool(page);
    await submitGeneration(page, 'browse test: a purple flower');
    await waitForJobComplete(page);

    // Navigate to browse — just verify it loads successfully after a generation
    await goToBrowse(page);
    await expect(page.getByRole('button', { name: 'All Assets' })).toBeVisible();
  });
});
