import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { submitGeneration, waitForJobComplete, getResultTiles } from '../../helpers/generation';
import { describeWithTestProvider } from '../../helpers/fixtures';
import {
  openSlideshowFromQueue,
  openSendToMenu,
  selectSendToTool,
  openGenerateMoreMenu,
  selectGenerateMoreTool,
  waitForToolViewReady,
} from '../../helpers/cross-tool';

describeWithTestProvider('Multi-Step Chains', () => {
  test('t2i -> send to edit -> generate', async ({ page }) => {
    // Step 1: Generate an image
    await goToTool(page);
    await submitGeneration(page, 'a red apple on a table');
    await waitForJobComplete(page);

    // Step 2: Send to image-to-image
    await openSlideshowFromQueue(page);
    await openSendToMenu(page);
    await selectSendToTool(page, 'Test Image Edit');

    // Step 3: Now in image-to-image tool, submit an edit
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-edit');
    await submitGeneration(page, 'make the apple green');
    await waitForJobComplete(page);

    // Verify both generations completed (at least one result visible)
    const tiles = await getResultTiles(page);
    await expect(tiles.first()).toBeVisible();
  });

  test('t2i -> generate more with alt tool -> generate', async ({ page }) => {
    // Step 1: Generate an image
    await goToTool(page);
    await submitGeneration(page, 'a snowy mountain peak');
    await waitForJobComplete(page);

    // Step 2: Generate more with alt tool
    await openSlideshowFromQueue(page);
    await openGenerateMoreMenu(page);
    await selectGenerateMoreTool(page, 'Test Alt Text-to-Image');

    // Step 3: Now in alt t2i tool, generate
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-model-alt');
    // The prompt should already be loaded from generate-more
    await page.getByRole('button', { name: /^Run/ }).click();
    await waitForJobComplete(page);

    // Verify generation completed
    const tiles = await getResultTiles(page);
    await expect(tiles.first()).toBeVisible();
  });
});
