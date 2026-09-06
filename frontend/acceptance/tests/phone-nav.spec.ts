import { expect, test, type Locator, type Page } from '@playwright/test';
import { createChat } from '../helpers/app';
import { settleAnyViewport } from '../helpers/viewport';

async function longPress(page: Page, target: Locator, ms = 650) {
  const box = await target.boundingBox();
  if (!box) throw new Error('no box for long-press target');
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
  await page.waitForTimeout(ms);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

/**
 * Phone lane, navigation model: the desktop sidebar is a drawer behind the
 * header's Menu button; it pushes the app aside, closes on any navigation or
 * a tap on the pushed app; detail screens carry a back chevron that pops the
 * hub's stack. There is no tab bar.
 */
test.describe('phone lane: drawer navigation', () => {
  test('menu drawer, links, back', async ({ page }) => {
    await page.goto('/chats');
    await settleAnyViewport(page);
    const chat = await createChat(page, 'Nav stack chat');
    await page.goto('/chats');
    await settleAnyViewport(page);
    const menu = page.getByRole('button', { name: 'Menu' });
    const back = page.getByRole('button', { name: 'Back' });
    const drawer = page.locator('.navigation-sidebar');

    // The drawer stays mounted and slides; closed = inert and hidden from AT.
    const open = () => expect(drawer).not.toHaveAttribute('aria-hidden', 'true');
    const closed = () => expect(drawer).toHaveAttribute('aria-hidden', 'true');

    // Open the chat once so it joins the working set, then back to the list.
    await page.locator('.cursor-pointer.group').filter({ hasText: 'Nav stack chat' }).first().click({ position: { x: 300, y: 24 } });
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
    await back.click();
    await expect(page).toHaveURL(/\/chats$/);

    // Hub: Menu opens the drawer; it is the desktop sidebar (links, working set, footer).
    await expect(menu).toBeVisible();
    await closed();
    await menu.click();
    await open();
    await expect(drawer).toContainText('Nav stack chat');
    await expect(drawer.getByRole('button', { name: 'Settings' })).toBeVisible();

    // Working-set row: no hover-only close X (it was an invisible target
    // that swallowed taps). Long-press → the row's sheet; Rename opens the
    // rename sheet, never an inline field inside the row.
    // The track is still sliding right after open(); press once it has settled.
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.compact-track')!).transform === 'matrix(1, 0, 0, 1, 0, 0)');
    const chatRow = drawer.locator('nav button', { hasText: 'Nav stack chat' }).first();
    await expect(chatRow.locator('xpath=..').locator('button[title], button:has(svg)').filter({ hasNotText: 'Nav stack chat' })).toHaveCount(0);
    await longPress(page, chatRow);
    const rowSheet = page.locator('[data-sheet-menu]').last();
    await expect(rowSheet).toBeVisible({ timeout: 5000 });
    await rowSheet.getByText('Rename', { exact: true }).click();
    const renameSheet = page.getByRole('dialog').filter({ has: page.locator('input[type="text"]') });
    await expect(renameSheet).toBeVisible({ timeout: 5000 });
    await expect(drawer.locator('input')).toHaveCount(0);
    await renameSheet.locator('input[type="text"]').fill('Nav stack chat renamed');
    await renameSheet.getByRole('button', { name: 'Save' }).click();
    await expect(drawer).toContainText('Nav stack chat renamed', { timeout: 5000 });
    await expect(renameSheet).toBeHidden();

    // A drawer link navigates and closes the drawer.
    await drawer.getByText('Boards', { exact: true }).first().click();
    await expect(page).toHaveURL(/\/boards$/);
    await closed();

    // Tapping the pushed app closes the drawer without navigating.
    await menu.click();
    await open();
    await page.mouse.click(370, 400);
    await closed();
    await expect(page).toHaveURL(/\/boards$/);

    // Chats → chat (push): back pops to the chats list; a hub root has no back.
    await page.goto('/chats');
    await settleAnyViewport(page);
    await page.locator('.cursor-pointer.group').filter({ hasText: 'Nav stack chat' }).first().click({ position: { x: 300, y: 24 } });
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));
    await expect(menu).toBeVisible();
    await back.click();
    await expect(page).toHaveURL(/\/chats$/);
    await expect(back).toHaveCount(0);

    // Tool: the header carries Run; back returns to the tools list.
    await page.goto('/tools');
    await settleAnyViewport(page);
    await page.goto(`/tools/test:text-to-image:test-model`);
    await settleAnyViewport(page);
    await expect(page.locator('.compact-header h1')).toContainText('Test Text-to-Image');
    await back.click();
    await expect(page).toHaveURL(/\/tools$/);
  });
});
