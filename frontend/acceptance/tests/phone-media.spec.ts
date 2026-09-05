import { mkdir } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { TEST_T2I_TOOL_ID, promptInput, waitForGeneratedMedia } from '../helpers/app';
import { auditHitTargets, auditHorizontalOverflow, expectNoOverflow, settleAnyViewport } from '../helpers/viewport';

/**
 * Phone lane, media interactions: generate one image through the compact
 * tool view, then exercise the touch paths that have no desktop equivalent:
 * long-press → context sheet, tap → slideshow, swipe up → info sheet, the
 * Library filter sheet. Screenshots land next to the hub shots.
 */

async function shot(page: Page, name: string) {
  await mkdir('acceptance/phone-shots', { recursive: true });
  await page.screenshot({ path: `acceptance/phone-shots/media-${name}.png` });
}

/** Press-and-hold at an element's centre using real touch events. */
async function longPress(page: Page, selector: string, ms = 650) {
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`no box for ${selector}`);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
  await page.waitForTimeout(ms);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

/** A real touch tap (touchstart/touchend) at an element's centre. */
async function tap(page: Page, locatorSel: string) {
  const box = await page.locator(locatorSel).first().boundingBox();
  if (!box) throw new Error(`no box for ${locatorSel}`);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

async function swipe(page: Page, from: [number, number], to: [number, number]) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: from[0], y: from[1] }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: to[0], y: to[1] }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

test.describe('phone lane: media touch paths', () => {
  test('generate, long-press menu, slideshow, info sheet, filter sheet', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto(`/tools/${TEST_T2I_TOOL_ID}`);
    await settleAnyViewport(page);
    const prompt = `phone lane ${Date.now()}`;
    await promptInput(page).fill(prompt);
    const run = page.locator('#compact-header-actions').getByTestId('tool-run-button');
    await expect(run).toBeEnabled({ timeout: 15000 });
    await run.click();
    const [media] = await waitForGeneratedMedia(page, {});
    await shot(page, 'tool-after-run');

    // Drawer: tap the handle to half, drag to full; the handle and a slice of
    // the hero stay visible at every height.
    const handleSel = '[aria-label="Toggle controls"]';
    const handle = page.locator(handleSel);
    await tap(page, handleSel);
    await page.waitForTimeout(350);
    await shot(page, 'tool-drawer-half');
    const box = await handle.boundingBox();
    expect(box!.y, 'handle stays below the header').toBeGreaterThan(96);
    await swipe(page, [195, box!.y + 4], [195, 80]);
    await page.waitForTimeout(400);
    await shot(page, 'tool-drawer-full');
    const full = await handle.boundingBox();
    expect(full!.y, 'handle visible at full height').toBeGreaterThan(48 + 96 - 8);
    await tap(page, handleSel);
    await page.waitForTimeout(350);

    // Leaving and coming back through the tools list keeps the prompt.
    await page.goto('/tools');
    await settleAnyViewport(page);
    await page.getByText('Test Text-to-Image', { exact: true }).first().click();
    await page.waitForURL(/\/tools\/test/, { timeout: 15000 });
    await settleAnyViewport(page);
    await expect(promptInput(page)).toContainText(prompt, { timeout: 10000 });

    await page.goto('/browse');
    await settleAnyViewport(page);
    const tile = `[data-testid="media-grid-item-${media.id}"]`;
    await expect(page.locator(tile)).toBeVisible({ timeout: 30000 });

    // Long-press → the media context menu as a bottom sheet.
    await longPress(page, tile);
    const menu = page.locator('[data-context-menu][data-sheet-menu]');
    await expect(menu).toBeVisible({ timeout: 5000 });
    await shot(page, 'context-sheet');
    const menuBox = await menu.boundingBox();
    expect(menuBox!.width, 'sheet spans the viewport').toBeGreaterThan(380);
    const hits = await auditHitTargets(page, 44, '[data-context-menu][data-sheet-menu]');
    expect(hits.small, `context sheet rows under 44px: ${hits.small.map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`).toHaveLength(0);
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden({ timeout: 5000 });

    // Tap → slideshow, no info panel, tab bar hidden.
    await page.locator(tile).tap();
    await expect(page.locator('[data-testid="media-info-panel"]')).toHaveCount(0);
    await expect(page.locator('.compact-tab-bar')).toBeHidden();
    await shot(page, 'slideshow');
    expectNoOverflow(await auditHorizontalOverflow(page), 'slideshow');

    // Swipe up → info sheet.
    await swipe(page, [195, 600], [195, 300]);
    await expect(page.locator('[data-testid="media-info-panel"]')).toBeVisible({ timeout: 5000 });
    await shot(page, 'slideshow-info');
    await page.keyboard.press('Escape');

    // Library filter sheet.
    await page.goto('/browse');
    await settleAnyViewport(page);
    await page.getByRole('button', { name: /Filters/ }).first().click();
    await page.waitForTimeout(400);
    await shot(page, 'filter-sheet');
    expectNoOverflow(await auditHorizontalOverflow(page), 'filter sheet');
  });
});
