import { expect, test } from '@playwright/test';
import {
  generateMedia,
  listMedia,
  openToolWithPendingInput,
  openToolById,
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

  test('dropping an existing asset into a tool reuses it without importing a duplicate', async ({ page }) => {
    const source = await generateMedia(page, `acceptance direct asset handoff ${Date.now()}`);
    const before = await listMedia(page, { page: 1, page_size: 200 });
    const copyRequests: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/generate\/copy-(?:audio-to-reference|video-to-reference|to-reference)/.test(request.url())) {
        copyRequests.push(request.url());
      }
    });

    await openToolById(page, TEST_I2I_TOOL_ID);
    const picker = page.locator('[data-drop-zone="media-picker-image"]');
    await picker.evaluate((element, mediaId) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.setData('application/x-media-id', String(mediaId));
      element.dispatchEvent(new DragEvent('drop', {
        bubbles: true,
        cancelable: true,
        dataTransfer,
      }));
    }, source.id);
    await expect(picker.getByText('1/3')).toBeVisible();
    const preview = picker.locator('img[alt="image 1"]');
    await expect(preview).toBeVisible();
    await expect(preview).toHaveAttribute('src', new RegExp(`/media/${source.id}/file$`));

    const after = await listMedia(page, { page: 1, page_size: 200 });
    expect(after.map((item) => item.id).sort()).toEqual(before.map((item) => item.id).sort());
    expect(copyRequests).toEqual([]);
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
