import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { submitGeneration, waitForJobComplete, getResultTiles } from '../../helpers/generation';
import { describeWithTestProvider } from '../../helpers/fixtures';

describeWithTestProvider('Generation Submission', () => {
  test('submit multiple jobs in sequence', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'first generation: mountains');
    await waitForJobComplete(page);

    // Submit second job
    await submitGeneration(page, 'second generation: ocean');
    await waitForJobComplete(page);

    // Should have at least 2 images in the queue panel
    const tiles = await getResultTiles(page);
    await expect(tiles.nth(1)).toBeVisible({ timeout: 5000 });
  });

  test('generation completes and shows result', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'test: a sunset over the ocean');
    await waitForJobComplete(page);
    const tiles = await getResultTiles(page);
    await expect(tiles.first()).toBeVisible();
  });
});
