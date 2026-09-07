import { expect, test, type Page } from '@playwright/test';
import { apiJSON, createBoard, createChat, createProject, promptInput, TEST_T2I_TOOL_ID } from '../helpers/app';
import { settleAnyViewport } from '../helpers/viewport';

async function generate(page: Page, label: string) {
  await page.goto(`/tools/${TEST_T2I_TOOL_ID}`);
  await settleAnyViewport(page);
  const prompt = `${label} ${Date.now()}`;
  const before = await apiJSON<any>(page, '/api/media?page=1&page_size=1&sort_by=created_desc');
  const lastId = before.items[0]?.id || 0;
  await promptInput(page).fill(prompt);
  await page.locator('#compact-header-actions').getByTestId('tool-run-button').click();
  let latest: any;
  await expect.poll(async () => {
    latest = (await apiJSON<any>(page, '/api/media?page=1&page_size=1&sort_by=created_desc')).items[0];
    return latest?.id || 0;
  }, { timeout: 30000 }).toBeGreaterThan(lastId);
  return latest;
}

async function renameFromHeader(page: Page, name: string) {
  await page.locator('.compact-header button').filter({ has: page.locator('h1') }).click();
  const sheet = page.locator('[data-sheet-layer]');
  await sheet.getByRole('textbox').fill(name);
  await sheet.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.locator('.compact-header h1')).toHaveText(name);
}

test('board has one editable header, complete options, and touch-based asset selection', async ({ page }) => {
  const media = await generate(page, 'board asset');
  const board = await createBoard(page, '');
  const project = await createProject(page, 'Phone board project');
  await page.goto(`/boards/${board.id}`);
  await settleAnyViewport(page);
  await expect(page.locator('.compact-header h1')).toHaveText('Name this board…');
  await expect(page.getByTitle('Board actions')).toBeHidden();
  await expect(page.getByText('Drop assets here', { exact: true })).toBeHidden();
  await renameFromHeader(page, 'My phone board');
  const section = page.getByRole('button', { name: 'Name this section…', exact: true });
  expect((await section.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await section.click();
  await page.locator('[data-board-section] input').fill('My section');
  await page.locator('[data-board-section] input').press('Enter');
  await expect(page.getByRole('button', { name: 'My section', exact: true })).toBeVisible();
  await page.locator('[data-board-section]').filter({ has: page.getByRole('button', { name: 'My section', exact: true }) }).getByRole('button', { name: 'Add assets', exact: true }).click();
  const picker = page.locator('[data-sheet-layer]');
  await picker.getByRole('button', { name: `Select asset ${media.asset_id}`, exact: true }).click();
  await picker.getByRole('button', { name: 'Add 1 asset', exact: true }).click();
  await expect(picker).toBeHidden();
  await expect(page.locator('[data-board-item="true"]')).toHaveCount(1);
  await page.locator('.compact-header').getByRole('button', { name: 'More', exact: true }).click();
  for (const name of ['Open', 'Rename', 'Move to project', 'Delete']) await expect(page.locator('[data-sheet-layer]').getByRole('button', { name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Move to project', exact: true }).click();
  await page.locator('[data-sheet-layer]').getByRole('button', { name: project.name, exact: true }).click();
  await expect.poll(async () => (await apiJSON<any>(page, `/api/boards/${board.id}`)).project_id).toBe(project.id);
  await page.reload();
  await settleAnyViewport(page);
  await expect(page.locator('.compact-header h1')).toHaveText('My phone board');
  await page.screenshot({ path: 'acceptance/phone-shots/board-touch-controls.png' });
});

for (const entity of ['chat', 'flow']) {
  test(`${entity} has one editable title and unified entity options`, async ({ page }) => {
    await page.goto(entity === 'chat' ? '/chats' : '/flows');
    await settleAnyViewport(page);
    if (entity === 'chat') {
      const chat = await createChat(page, 'Original chat');
      await page.goto(`/chat/${chat.id}`);
    } else {
      await page.getByRole('button', { name: 'New' }).first().click();
      await page.waitForURL(/\/flows\/[^/]+$/);
    }
    await settleAnyViewport(page);
    await renameFromHeader(page, `Phone ${entity}`);
    await expect(page.getByRole('button', { name: `Phone ${entity}`, exact: true })).toHaveCount(0);
    await page.locator('.compact-header').getByRole('button', { name: 'More', exact: true }).click();
    for (const name of ['Rename', 'Move to project', 'Make a copy', 'Delete']) await expect(page.locator('[data-sheet-layer]').getByRole('button', { name, exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await page.reload();
    await settleAnyViewport(page);
    await expect(page.locator('.compact-header h1')).toHaveText(`Phone ${entity}`);
  });
}

test('gallery follows the finger before release, advances smoothly, and cancels a short drag', async ({ page }) => {
  test.setTimeout(120000);
  await generate(page, 'gallery first');
  const newest = await generate(page, 'gallery second');
  await page.goto('/browse');
  await settleAnyViewport(page);
  await page.locator(`[data-testid="media-grid-item-${newest.id}"]`).tap();
  const hero = page.locator('[data-gallery-picture]');
  await expect(hero).toBeVisible();
  const image = hero.locator('img');
  const beforeSrc = await image.getAttribute('src');
  const before = (await hero.boundingBox())!;
  const cdp = await page.context().newCDPSession(page);
  const y = before.y + before.height / 2;
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 300, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 160, y }] });
  await expect.poll(async () => (await hero.boundingBox())!.x).toBeLessThan(before.x - 100);
  expect(await image.getAttribute('src')).toBe(beforeSrc);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect(image).not.toHaveAttribute('src', beforeSrc!);
  await expect.poll(async () => Math.abs((await hero.boundingBox())!.x - before.x)).toBeLessThan(2);
  const nextSrc = await image.getAttribute('src');
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 200, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 180, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(async () => Math.abs((await hero.boundingBox())!.x - before.x)).toBeLessThan(2);
  expect(await image.getAttribute('src')).toBe(nextSrc);
  await cdp.detach();
});
