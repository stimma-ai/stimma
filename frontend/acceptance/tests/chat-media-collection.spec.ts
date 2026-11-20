import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { apiJSON, createChat, waitForShell } from '../helpers/app';

// An agent's image set in chat: browse it in place, in two views and two homes,
// and carry picks to the composer.
test('a chat collection browses in place and sends picks to the composer', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const fixture = await readFile(new URL('../../public/logo.png', import.meta.url));
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const ids: number[] = [];
  for (let i = 0; i < 16; i++) {
    const upload = await page.request.post('/api/generate/upload-bulk', {
      headers: { 'X-Profile-ID': profileId! },
      multipart: { files: { name: `option-${i}.png`, mimeType: 'image/png',
        buffer: Buffer.concat([fixture, Buffer.from(`\nchat-collection-${i}-${Date.now()}`)]) } },
    });
    expect(upload.ok()).toBe(true);
    ids.push((await upload.json()).results[0].media_id);
  }
  const chat = await createChat(page, 'Collection');
  const response = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: {
      title: 'Directions',
      rows: ids.map((media_id, i) => ({ id: i, input: { type: 'output_only' }, output: { status: 'complete', media_id } })),
    } }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);
  const dismiss = page.getByTestId('readiness-dismiss');
  if (await dismiss.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false)) await dismiss.click();

  const collection = page.locator(`[data-item-id="${response.id}"]`);
  const panelCollection = page.getByTestId('media-collection');
  const hero = page.getByTestId('media-collection-hero');
  // The strip marks the picture on show.
  const current = collection.locator('[data-tile][aria-current="true"]');
  const bar = page.getByTestId('media-selection-bar');
  const attachments = page.locator('.chat-attachments > div');

  // More than fits opens in Preview, whose height leaves the composer in view.
  await expect(current).toHaveAttribute('data-tile', '0');
  await expect(collection.locator('[data-tile]')).toHaveCount(16);
  const messages = page.locator('[data-chat-scroller]');
  expect((await panelCollection.boundingBox())!.height).toBeLessThanOrEqual((await messages.boundingBox())!.height);

  await collection.locator('[data-tile="3"]').click();
  await expect(current).toHaveAttribute('data-tile', '3');
  await page.keyboard.press('ArrowRight');
  await expect(current).toHaveAttribute('data-tile', '4');
  await collection.locator('[data-tile="11"]').click();
  await expect(current).toHaveAttribute('data-tile', '11');

  // The picture opens the slideshow, and Escape comes straight back.
  await hero.locator('.group.cursor-pointer').click();
  const slideshowPicture = page.locator('[data-gallery-picture] img');
  await expect(slideshowPicture).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(slideshowPicture).toHaveCount(0);
  await expect(hero).toBeVisible();

  // Where the slideshow ends is where the collection picks up, with focus.
  await hero.locator('.group.cursor-pointer').click();
  await expect(slideshowPicture).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Escape');
  await expect(slideshowPicture).toHaveCount(0);
  await expect(current).toHaveAttribute('data-tile', '13');
  await expect(collection.locator('[data-tile="13"]')).toBeFocused();
  await collection.locator('[data-tile="11"]').click();
  await expect(current).toHaveAttribute('data-tile', '11');

  // Picks carry between views and dock on the composer.
  await hero.hover();
  await hero.getByRole('checkbox', { name: 'Select this image' }).click();
  await expect(bar).toContainText('1 selected');
  await collection.getByRole('radio', { name: 'Grid' }).click();
  // Collapsed, the grid shows three rows (how many columns depends on the width).
  await expect(collection.locator('[data-tile="15"]')).toHaveCount(0);
  const shown = await collection.locator('[data-tile]').count();
  const last = collection.locator(`[data-tile="${shown - 1}"]`);
  await expect(last).toContainText(`+${16 - shown + 1}`);
  await last.click();
  await expect(collection.locator('[data-tile="15"]')).toBeVisible();
  await expect(collection.locator('[data-tile="11"]').getByRole('checkbox')).toHaveAttribute('aria-checked', 'true');
  await collection.locator('[data-tile="2"]').click();
  await expect(bar).toContainText('2 selected');
  await expect(hero).toHaveCount(0);

  // Compare opens on exactly two.
  await bar.getByRole('button', { name: 'Compare' }).click();
  await expect(page.locator('[data-escape-layer].bg-black')).toBeVisible();
  await page.keyboard.press('Escape');

  await bar.getByRole('button', { name: 'Add to message' }).click();
  await expect(attachments).toHaveCount(2);
  await expect(bar).toHaveCount(0);

  // The panel takes the same collection; a chip keeps its place in the chat.
  await collection.getByRole('button', { name: 'Open in panel' }).click();
  await expect(collection.getByText('in panel')).toBeVisible();
  await expect(collection.getByTestId('media-collection')).toHaveCount(0);
  await expect(panelCollection.locator('[data-tile]')).toHaveCount(16);
  await expect(panelCollection.locator('[data-tile="2"]').getByTitle('In your message')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(collection.getByTestId('media-collection')).toBeVisible();

  // Space on a control inside the card presses that control, not the image.
  await collection.getByRole('radio', { name: 'Preview' }).click();
  await collection.locator('[data-tile="5"]').click();
  await hero.hover();
  const add = hero.getByRole('button', { name: 'Add to message' });
  await add.focus();
  await page.keyboard.press('Space');
  await expect(hero.getByRole('button', { name: 'Remove from message' })).toBeVisible();
  await expect(bar).toHaveCount(0);
});

test('single results and short sets need no paging', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const fixture = await readFile(new URL('../../public/logo.png', import.meta.url));
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const upload = await page.request.post('/api/generate/upload-bulk', {
    headers: { 'X-Profile-ID': profileId! },
    multipart: { files: { name: 'one.png', mimeType: 'image/png', buffer: Buffer.concat([fixture, Buffer.from(`\nsingle-${Date.now()}`)]) } },
  });
  const media_id = (await upload.json()).results[0].media_id;
  const chat = await createChat(page, 'One');
  const post = (rows: unknown[]) => apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: { rows } }) },
  } as any);
  const row = (id: number, output: Record<string, unknown>) => ({ id, input: { type: 'output_only' }, output });
  const single = await post([row(0, { status: 'complete', media_id })]);
  const failed = await post([row(0, { status: 'complete', media_id }), row(1, { status: 'failed', error_summary: 'Out of memory' })]);
  await page.goto(`/chat/${chat.id}`);
  await expect(page.locator(`[data-item-id="${single.id}"] [role="radiogroup"]`)).toHaveCount(0);
  await expect(page.locator(`[data-item-id="${failed.id}"]`).getByText('Out of memory')).toBeVisible();
  await expect(page.locator(`[data-item-id="${failed.id}"]`).getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
});


test('chat videos loop silently and play their sound once on request', async ({ page }, testInfo) => {
  const source = testInfo.outputPath('chat-video.mp4');
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i',
    'testsrc2=duration=8:size=320x180:rate=25', '-f', 'lavfi', '-i',
    'sine=duration=8:sample_rate=48000', '-c:v', 'libx264', '-preset', 'ultrafast',
    '-c:a', 'aac', '-shortest', source], { timeout: 15_000 });
  await page.goto('/browse');
  await waitForShell(page);
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const uploaded = await page.request.post('/api/generate/upload-bulk', {
    headers: { 'X-Profile-ID': profileId! },
    multipart: { files: { name: 'chat-video.mp4', mimeType: 'video/mp4', buffer: await readFile(source) } },
  });
  expect(uploaded.ok()).toBe(true);
  const media_id = (await uploaded.json()).results[0].media_id;
  const chat = await createChat(page, 'Video');
  await apiJSON(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: {
      rows: [{ id: 1, input: { type: 'output_only' }, output: { status: 'complete', media_id } }],
    } }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);
  const hero = page.getByTestId('media-collection-hero');
  // No hover, no play button: the video just loops without sound.
  await expect(hero.getByRole('button', { name: 'Play video' })).toHaveCount(0);
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && v.muted && v.loop)).toBe(true);
  const toolbar = hero.getByTestId('media-collection-toolbar');
  // The speaker plays one pass with sound from the top.
  await toolbar.getByRole('button', { name: /Play sound once/ }).click();
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && !v.muted && !v.loop)).toBe(true);
  await toolbar.getByRole('button', { name: 'Stop sound' }).click();
  await expect.poll(() => hero.locator('video').evaluate(v => !v.paused && v.muted && v.loop)).toBe(true);
  await toolbar.getByRole('button', { name: 'Add to message' }).click();
  await expect(toolbar.getByRole('button', { name: 'Remove from message' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('chat-video.png') });
  await hero.locator('[data-video-surface]').click();
  await expect(page.locator('video[data-gallery-picture]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('video[data-gallery-picture]')).toHaveCount(0);
  await expect(toolbar).toBeVisible();
});
