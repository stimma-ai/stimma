import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { apiJSON, createChat, waitForShell } from '../helpers/app';

// Tap opens, long-press selects, a swipe pages the picture (DESIGN.md §1.11).
test('a chat collection works by touch on a phone', async ({ page, context }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const fixture = await readFile(new URL('../../public/logo.png', import.meta.url));
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const rows = [];
  for (let i = 0; i < 12; i++) {
    const upload = await page.request.post('/api/generate/upload-bulk', {
      headers: { 'X-Profile-ID': profileId! },
      multipart: { files: { name: `option-${i}.png`, mimeType: 'image/png',
        buffer: Buffer.concat([fixture, Buffer.from(`\nphone-collection-${i}-${Date.now()}`)]) } },
    });
    rows.push({ id: i, input: { type: 'output_only' }, output: { status: 'complete', media_id: (await upload.json()).results[0].media_id } });
  }
  const chat = await createChat(page, 'Phone collection');
  await apiJSON<any>(page, `/api/chats/${chat.id}/items`, {
    method: 'POST', data: { item_type: 'media_display', item_metadata: JSON.stringify({ display_data: { title: 'Directions', rows } }) },
  } as any);
  await page.goto(`/chat/${chat.id}`);

  const collection = page.getByTestId('media-collection');
  const hero = page.getByTestId('media-collection-hero');
  await expect(hero.getByRole('button', { name: '1 / 12' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

  // Every visible control in the card is a real touch target.
  const small = await collection.evaluate(root => [...root.querySelectorAll('button,input')].filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && (r.width < 44 || r.height < 44);
  }).map(el => el.getAttribute('aria-label') || el.textContent?.trim()));
  expect(small).toEqual([]);

  const session = await context.newCDPSession(page);
  const touch = (type: string, x?: number, y?: number) => session.send('Input.dispatchTouchEvent', {
    type: type as any, touchPoints: x == null ? [] : [{ x, y: y! }],
  });

  const box = (await hero.boundingBox())!;
  const y = box.y + box.height / 2;
  await touch('touchStart', box.x + box.width - 40, y);
  for (const x of [box.width - 80, box.width - 160, box.width - 260]) await touch('touchMove', box.x + x, y);
  await touch('touchEnd');
  await expect(hero.getByRole('button', { name: '2 / 12' })).toBeVisible();

  const tile = (await collection.locator('[data-tile="4"]').boundingBox())!;
  await touch('touchStart', tile.x + tile.width / 2, tile.y + tile.height / 2);
  await page.waitForTimeout(550);
  await touch('touchEnd');
  const bar = page.getByTestId('media-selection-bar');
  await expect(bar).toContainText('1 selected');
  await bar.getByRole('button', { name: 'Add to message' }).click();
  await expect(page.locator('.chat-attachments > div')).toHaveCount(1);

  // Full screen keeps every image reachable and returns to the message.
  await collection.getByRole('button', { name: 'More options' }).click();
  await page.getByText('Open full screen').click();
  await collection.getByRole('radio', { name: 'Grid' }).click();
  await expect(collection.locator('[data-tile]')).toHaveCount(12);
  await collection.getByRole('button', { name: 'Close panel' }).click();
  await expect(page.locator('[data-chat-scroller] [data-testid="media-collection"]')).toBeVisible();
});
