import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { apiJSON, createChat, getMedia, waitForShell } from '../helpers/app';

test('chat slideshow stays live and preserves the selected image across batches', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = class extends NativeWebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        (window as any).__acceptanceChatSocket = this;
      }
    };
  });
  await page.goto('/browse');
  await waitForShell(page);
  const images = [];
  const fixture = await readFile(new URL('../../public/logo.png', import.meta.url));
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  for (let i = 0; i < 3; i++) {
    const upload = await page.request.post('/api/generate/upload-bulk', {
      headers: { 'X-Profile-ID': profileId! },
      multipart: { files: { name: `option-${i}.png`, mimeType: 'image/png',
        buffer: Buffer.concat([fixture, Buffer.from(`\nchat-slideshow-${i}-${Date.now()}`)]) } },
    });
    expect(upload.ok()).toBe(true);
    const result = (await upload.json()).results[0];
    expect(result.status).toBe('success');
    images.push(await getMedia(page, result.media_id));
  }
  const chat = await createChat(page, 'Live slideshow');
  const display = (ids: Array<number | null>, title = 'First batch') => ({
    title, current: ids.filter(Boolean).length, total: ids.length, status: 'in_progress',
    previews: ids.filter(Boolean),
    preview_slots: ids.map(id => ({ media_ids: id ? [id] : [], status: id ? 'completed' : 'pending' })),
  });
  const progress = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'progress_display',
      item_metadata: JSON.stringify({ display_data: display([null, images[1].id]) }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);
  await expect(page.getByRole('button', { name: 'Option 1 · pending', exact: true })).toBeDisabled();
  const dismiss = page.getByTestId('readiness-dismiss');
  if (await dismiss.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false)) {
    await dismiss.click();
  }
  await page.getByRole('button', { name: 'Option 2', exact: true }).click();
  const hero = page.locator('[data-gallery-picture] img');
  await expect(hero).toHaveAttribute('src', new RegExp(images[1].file_hash!));
  await hero.click();
  const picture = page.locator('[data-gallery-picture]');
  const zoom = await picture.getAttribute('style');
  await page.evaluate(payload => {
    (window as any).__acceptanceChatSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(payload) }));
  }, { event: 'chat_item_updated', data: {
    chat_id: chat.id,
    item: { ...progress, item_metadata: JSON.stringify({ display_data: display([images[0].id, images[1].id]) }) },
  } });
  await apiJSON(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'progress_display',
      item_metadata: JSON.stringify({ display_data: display([images[2].id], 'Second batch') }) },
  } as any);
  await expect(page.getByTitle('Next (→ or D)', { exact: true })).toBeVisible();
  await expect(hero).toHaveAttribute('src', new RegExp(images[1].file_hash!));
  await expect(picture).toHaveAttribute('style', zoom!);
  await page.keyboard.press('ArrowLeft');
  await expect(hero).toHaveAttribute('src', new RegExp(images[0].file_hash!));
  await page.keyboard.press('ArrowRight');
  await expect(hero).toHaveAttribute('src', new RegExp(images[1].file_hash!));
  await page.keyboard.press('ArrowRight');
  await expect(hero).toHaveAttribute('src', new RegExp(images[2].file_hash!));
  await expect(page.getByText('Second batch · Option 1', { exact: true })).toBeVisible();

  // A curated response neither duplicates nor reorders the slideshow.
  const response = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display',
      item_metadata: JSON.stringify({ display_data: { title: 'Favorites', rows: [images[2], images[0]].map((image, i) => ({
        id: i, input: { type: 'output_only' }, output: { status: 'complete', media_id: image.id },
      })) } }) },
  } as any);
  await expect(page.getByTitle('Next (→ or D)', { exact: true })).toBeHidden();
  await page.keyboard.press('Escape');
  await page.locator(`[data-item-id="${response.id}"] .media-display .group.cursor-pointer`).first().click();
  await expect(hero).toHaveAttribute('src', new RegExp(images[2].file_hash!));
  await page.keyboard.press('ArrowLeft');
  await expect(hero).toHaveAttribute('src', new RegExp(images[1].file_hash!));
  await page.screenshot({ path: testInfo.outputPath('live-chat-slideshow.png') });
});

test('Escape closes only the chat slideshow before older window shortcuts run', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const upload = await page.request.post('/api/generate/upload-bulk', {
    headers: { 'X-Profile-ID': profileId! },
    multipart: { files: { name: 'slideshow-escape.png', mimeType: 'image/png',
      buffer: await readFile(new URL('../../public/logo.png', import.meta.url)) } },
  });
  expect(upload.ok()).toBe(true);
  const image = (await upload.json()).results[0];
  expect(image.status).toBe('success');
  const chat = await createChat(page, 'Slideshow dismissal');
  const response = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display',
      item_metadata: JSON.stringify({ display_data: { rows: [{
        id: 0, input: { type: 'output_only' }, output: { status: 'complete', media_id: image.media_id },
      }] } }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);
  const dismiss = page.getByTestId('readiness-dismiss');
  if (await dismiss.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false)) {
    await dismiss.click();
  }
  // Register before the slideshow, like a previously mounted navigation surface.
  await page.evaluate(() => {
    (window as any).__chatEscapeCount = 0;
    window.addEventListener('keydown', event => {
      if (event.key === 'Escape') (window as any).__chatEscapeCount++;
    });
  });
  const preview = page.locator(`[data-item-id="${response.id}"] .media-display .group.cursor-pointer`).first();
  const hero = page.locator('[data-gallery-picture] img');
  for (let i = 0; i < 2; i++) {
    await page.getByRole('textbox', { name: 'Type a message...' }).focus();
    await preview.click();
    await expect(hero).toBeVisible();
    if (i === 1) {
      await hero.click({ button: 'right' });
      await expect(page.locator('[data-context-menu]')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.locator('[data-context-menu]')).toHaveCount(0);
      await expect(hero).toBeVisible();
    }
    await page.keyboard.press('Escape');
    await expect(hero).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
    await expect(preview).toBeVisible();
    expect(await page.evaluate(() => (window as any).__chatEscapeCount)).toBe(0);
  }
});
