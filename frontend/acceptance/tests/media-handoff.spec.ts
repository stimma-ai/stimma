import { expect, test } from '@playwright/test';
import {
  generateMedia,
  openToolWithPendingInput,
  seedPendingToolInput,
  submitGeneration,
  TEST_I2I_TOOL_ID,
  TEST_UPSCALE_TOOL_ID,
  waitForGeneratedFromSource,
  waitForShell,
} from '../helpers/app';

test.describe('media handoff acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('generated media can be handed to image-to-image and submitted as a source input', async ({ page }) => {
    const source = await generateMedia(page, `acceptance handoff source ${Date.now()}`);
    const prompt = `acceptance image handoff edit ${Date.now()}`;

    await seedPendingToolInput(page, TEST_I2I_TOOL_ID, [source.id]);
    await openToolWithPendingInput(page, TEST_I2I_TOOL_ID);
    await expect(page.locator('[data-drop-zone="media-picker-image"]').getByText('1/3')).toBeVisible();

    await submitGeneration(page, prompt);

    const outputs = await waitForGeneratedFromSource(page, TEST_I2I_TOOL_ID, [source.id]);
    expect(outputs[0].generation_metadata).toContain(String(source.id));
  });

  test('generated media can be handed to upscale and submitted as a source input', async ({ page }) => {
    const source = await generateMedia(page, `acceptance upscale source ${Date.now()}`);

    await seedPendingToolInput(page, TEST_UPSCALE_TOOL_ID, [source.id]);
    await openToolWithPendingInput(page, TEST_UPSCALE_TOOL_ID);
    await expect(page.locator('[data-drop-zone="media-picker-image"]').getByText('1/1')).toBeVisible();

    await page.getByRole('button', { name: /^Run/ }).click();

    const outputs = await waitForGeneratedFromSource(page, TEST_UPSCALE_TOOL_ID, [source.id]);
    expect(outputs[0].generation_metadata).toContain(String(source.id));
  });

  test('multiple generated media can be handed to image-to-image as a media batch', async ({ page }) => {
    const stamp = Date.now();
    const first = await generateMedia(page, `acceptance handoff batch first ${stamp}`);
    const second = await generateMedia(page, `acceptance handoff batch second ${stamp}`);
    const prompt = `acceptance image handoff batch ${stamp}`;

    await seedPendingToolInput(page, TEST_I2I_TOOL_ID, [first.id, second.id], { mode: 'batch' });
    await openToolWithPendingInput(page, TEST_I2I_TOOL_ID);

    await submitGeneration(page, prompt);

    const firstOutputs = await waitForGeneratedFromSource(page, TEST_I2I_TOOL_ID, [first.id]);
    const secondOutputs = await waitForGeneratedFromSource(page, TEST_I2I_TOOL_ID, [second.id]);
    expect(firstOutputs.length).toBeGreaterThan(0);
    expect(secondOutputs.length).toBeGreaterThan(0);
  });
});
