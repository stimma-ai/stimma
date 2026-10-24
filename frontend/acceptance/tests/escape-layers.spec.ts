import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { apiJSON, createChat, getMedia, waitForShell } from '../helpers/app';
import type { Page } from '@playwright/test';

async function uploadImage(page: Page) {
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const upload = await page.request.post('/api/generate/upload-bulk', {
    headers: { 'X-Profile-ID': profileId! },
    multipart: { files: { name: 'escape-layers.png', mimeType: 'image/png',
      buffer: await readFile(new URL('../../public/logo.png', import.meta.url)) } },
  });
  expect(upload.ok()).toBe(true);
  const image = (await upload.json()).results[0];
  expect(image.status).toBe('success');
  return getMedia(page, image.media_id);
}

async function dismissReadiness(page: Page) {
  const dismiss = page.getByTestId('readiness-dismiss');
  if (await dismiss.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false)) await dismiss.click();
}

test('Escape does not navigate away from Upload or Lineage, including a cached Upload view', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const image = await uploadImage(page);
  await page.goto('/upload');
  await expect(page.getByRole('button', { name: 'Browse Files', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/upload$/);
  await page.getByRole('button', { name: 'Tools', exact: true }).first().click();
  await expect(page).toHaveURL(/\/tools$/);
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/tools$/);
  await page.goto(`/lineage/${image.id}`);
  await expect(page.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(new RegExp(`/lineage/${image.id}$`));
});

test('Escape dismisses provider setup before Settings without changing the route', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Chat Models', exact: true }).click();
  await page.getByRole('button', { name: /^Add OpenAI Compatible Endpoint/ }).click();
  await expect(page.getByRole('heading', { name: 'Add OpenAI Compatible Endpoint', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Add OpenAI Compatible Endpoint', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/browse$/);
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-modal-layer]')).toHaveCount(0);
  await expect(page).toHaveURL(/\/browse$/);
});

test('Escape in an active chat composer keeps its existing Stop shortcut', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const chat = await createChat(page, 'Escape stops the active chat');
  await page.route(`**/api/chats/${chat.id}/plan-status`, route => route.fulfill({ json: { has_plan: true, status: 'running' } }));
  let stops = 0;
  await page.route(`**/api/chats/${chat.id}/stop`, route => { stops++; return route.fulfill({ json: {} }); });
  await page.goto(`/chat/${chat.id}`);
  await dismissReadiness(page);
  await expect(page.getByTitle('Stop', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Type a message...' }).press('Escape');
  await expect(page.getByTitle('Stop', { exact: true })).toBeVisible();
  await expect.poll(() => stops).toBe(1);
});

test('Escape dismisses a Settings menu before Settings itself', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Markers', exact: true }).click();
  await page.getByRole('button', { name: 'Add Marker', exact: true }).click();
  await page.getByPlaceholder('Marker name').last().locator('..').getByTitle('More options', { exact: true }).click();
  await expect(page.locator('[data-marker-menu]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-marker-menu]')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-modal-layer]')).toHaveCount(0);
});

test('Escape dismisses Settings without also clearing the chat selection underneath', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const first = await createChat(page, 'Selected chat one');
  const second = await createChat(page, 'Selected chat two');
  await page.goto('/chats');
  await page.getByTestId(`chat-row-${first.id}`).getByRole('button').click();
  await page.getByTestId(`chat-row-${second.id}`).getByRole('button').click();
  const selection = page.getByTitle('Delete selected', { exact: true });
  await expect(selection).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-modal-layer]')).toHaveCount(0);
  await expect(selection).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(selection).toBeHidden();
});

test('Escape inside a package cover dismisses its slideshow', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const image = await uploadImage(page);
  const bundle = await apiJSON<any>(page, '/api/packages', { method: 'POST', data: {
    title: 'Escape from a package', media_ids: [image.id],
  } } as any);
  const chat = await createChat(page, 'Package dismissal');
  const response = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: { rows: [{
      id: 0, input: { type: 'output_only' }, output: { status: 'complete', media_id: bundle.media_id },
    }] } }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);
  await dismissReadiness(page);
  const preview = page.locator(`[data-item-id="${response.id}"] .media-display .group.cursor-pointer`).first();
  await preview.click();
  const cover = page.frameLocator('iframe[title="Package cover"]');
  await expect(cover.locator('body')).toBeVisible();
  await cover.locator('body').evaluate(body => {
    const layer = document.createElement('div');
    layer.id = 'cover-layer';
    layer.tabIndex = 0;
    layer.textContent = 'Cover layer';
    layer.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); layer.remove(); }
    });
    body.append(layer);
  });
  await cover.locator('#cover-layer').press('Escape');
  await expect(cover.locator('#cover-layer')).toHaveCount(0);
  await expect(page.locator('[data-escape-layer][data-drop-zone]')).toBeVisible();
  await cover.locator('body').press('Escape');
  await expect(page.locator('[data-escape-layer][data-drop-zone]')).toHaveCount(0);
  await expect(preview).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
});

for (const kind of ['set', 'grid', 'layout']) {
  test(`Escape dismisses ${kind === 'layout' ? 'a layout frame' : `a ${kind} member before its slideshow`} without navigating`, async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const image = await uploadImage(page);
    const collection = await apiJSON<any>(page, '/api/media/sets', {
      method: 'POST', data: { media_ids: [image.id], title: 'Dismiss the collection' },
    } as any);
    if (kind !== 'set') {
      // Exercise the other viewers against the same real retained media.
      const format = kind === 'grid' ? 'stimmagrid.json' : 'stimmalayout';
      await page.route(new RegExp(`/api/media/${collection.media_id}(?:\\?.*)?$`), async route => {
        const response = await route.fetch();
        await route.fulfill({ json: { ...(await response.json()), file_format: format } });
      });
      await page.route(`**/api/assets/item/${collection.asset_id}/browser*`, async route => {
        const response = await route.fetch();
        await route.fulfill({ json: { ...(await response.json()), file_format: format } });
      });
      await page.route(`**/api/media/${collection.media_id}/content`, route => route.fulfill({ json: {
        version: 1, title: 'Dismiss the collection', rows: 1, cols: 1,
        cells: [{ row: 0, col: 0, resolved: image }],
      } }));
      if (kind === 'layout') await page.route(`**/api/media/${collection.media_id}/layout-html`, route => route.fulfill({
        contentType: 'text/html', body: '<html data-stimma-width="800" data-stimma-height="600"><body><button>Layout control</button></body></html>',
      }));
    }
    const chat = await createChat(page, `Escape from a ${kind}`);
    const response = await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
      method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: { rows: [{
        id: 0, input: { type: 'output_only' }, output: { status: 'complete', media_id: collection.media_id },
      }] } }) },
    } as any);
    await page.goto(`/chat/${chat.id}`);
    await dismissReadiness(page);
    const preview = page.locator(`[data-item-id="${response.id}"] .media-display .group.cursor-pointer`).first();
    await preview.click();
    const slideshow = page.locator('[data-escape-layer][data-drop-zone]');
    await expect(slideshow).toBeVisible();
    if (kind === 'layout') {
      await slideshow.frameLocator('iframe').getByRole('button', { name: 'Layout control' }).press('Escape');
    } else {
      await slideshow.locator(kind === 'grid' ? 'td .cursor-pointer' : '.group.cursor-pointer').first().click();
      await expect(page.locator('[data-gallery-picture] img')).toBeVisible();
      const back = page.getByTitle(kind === 'grid' ? 'Return to grid overview (Esc)' : 'Exit set and return to main slideshow', { exact: true });
      await expect(back).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(back).toHaveCount(0);
      await expect(page.locator('[data-gallery-picture] img')).toHaveCount(0);
      await expect(slideshow).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
      await page.keyboard.press('Escape');
    }
    await expect(slideshow).toHaveCount(0);
    await expect(preview).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
  });
}
