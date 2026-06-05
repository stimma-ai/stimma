import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { submitGeneration, waitForJobComplete } from '../../helpers/generation';
import { describeWithTestProvider } from '../../helpers/fixtures';
import {
  openSlideshowFromQueue,
  openSendToMenu,
  selectSendToTool,
  waitForToolViewReady,
} from '../../helpers/cross-tool';

describeWithTestProvider('Send To Tool', () => {
  test('send t2i result to image-to-image', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a landscape with mountains');
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openSendToMenu(page);
    await selectSendToTool(page, 'Test Image Edit');

    // Should navigate to the image-to-image tool
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-edit');
  });

  test('send t2i result to upscale', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a detailed flower macro shot');
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openSendToMenu(page);
    await selectSendToTool(page, 'Test Upscale');

    // Should navigate to the upscale tool
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-upscale');
  });

  test('send t2i result to image-to-video', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a calm ocean sunset');
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openSendToMenu(page);
    await selectSendToTool(page, 'Test Image-to-Video');

    // Should navigate to the i2v tool
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-i2v');
  });

  test('send t2i result to inpaint', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a portrait with a plain background');
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openSendToMenu(page);
    await selectSendToTool(page, 'Test Inpaint');

    // Should navigate to the inpaint tool
    await waitForToolViewReady(page);
    expect(page.url()).toContain('test-inpaint');
  });
});
