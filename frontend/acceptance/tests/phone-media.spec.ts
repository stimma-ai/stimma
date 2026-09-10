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
    // Scoped to the app: the drawer is mounted (off-screen) and lists the same tool.
    await page.locator('.compact-pushed').getByText('Test Text-to-Image', { exact: true }).first().click();
    await page.waitForURL(/\/tools\/test/, { timeout: 15000 });
    await settleAnyViewport(page);
    await expect(promptInput(page)).toContainText(prompt, { timeout: 10000 });

    await page.goto('/browse');
    await settleAnyViewport(page);
    const tile = `[data-testid="media-grid-item-${media.id}"]`;
    await expect(page.locator(tile)).toBeVisible({ timeout: 30000 });

    // Long-press selects the tile (selection mode); a second long-press on
    // the selected tile opens the media context menu as a bottom sheet.
    await longPress(page, tile);
    await expect(page.locator(tile)).toHaveClass(/\bselected\b/, { timeout: 5000 });
    await expect(page.locator('[data-context-menu][data-sheet-menu]')).toHaveCount(0);
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
    // Escape also clears the selection, so the next tap navigates.
    await expect(page.locator(tile)).not.toHaveClass(/\bselected\b/);

    // Tap → slideshow, no info panel, header hidden.
    await page.locator(tile).tap();
    await expect(page.locator('[data-testid="media-info-panel"]')).toHaveCount(0);
    await expect(page.locator('.compact-header')).toBeHidden();
    await shot(page, 'slideshow');
    expectNoOverflow(await auditHorizontalOverflow(page), 'slideshow');

    // Native phones keep this chrome tier while rotating. Pin it here so the
    // browser lane can exercise both landscape safe areas on the real view.
    await page.evaluate(async () => {
      const { setViewportOverride } = await import('/src/composables/useViewport.ts');
      setViewportOverride({ tier: 'compact', pointer: 'coarse' });
      (window as any).slideshowImageBeforeRotation = document.querySelector('img[fetchpriority="high"]');
    });
    for (const [left, right] of [[44, 0], [0, 44]]) {
      await page.setViewportSize({ width: 844, height: 390 });
      await page.evaluate(({ left, right }) => {
        document.documentElement.style.setProperty('--safe-left', `${left}px`);
        document.documentElement.style.setProperty('--safe-right', `${right}px`);
        document.documentElement.style.setProperty('--safe-bottom', '21px');
      }, { left, right });
      await expect(page.getByRole('button', { name: 'Close slideshow', exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.querySelector('img[fetchpriority="high"]') === (window as any).slideshowImageBeforeRotation)).toBe(true);
      const close = await page.getByRole('button', { name: 'Close slideshow', exact: true }).boundingBox();
      expect(close!.x).toBeGreaterThanOrEqual(left);
      expect(close!.x + close!.width).toBeLessThanOrEqual(844 - right);
      for (const name of ['Info', 'Full screen']) {
        const button = await page.getByRole('button', { name, exact: true }).boundingBox();
        expect(button!.x).toBeGreaterThanOrEqual(left);
        expect(button!.x + button!.width).toBeLessThanOrEqual(844 - right);
      }
      const buttons = await page.locator('.slideshow-control-bar button').evaluateAll(elements => elements.map(el => {
        const box = el.getBoundingClientRect(); return { left: box.left, right: box.right };
      }));
      expect(buttons.every(box => box.left >= left && box.right <= 844 - right)).toBe(true);
    }
    // Hiding the strip must not put the remaining controls on the home indicator.
    await page.getByRole('button', { name: 'More', exact: true }).click();
    await page.getByRole('button', { name: /Filmstrip/ }).click();
    const play = await page.getByRole('button', { name: 'Play slideshow', exact: true }).boundingBox();
    expect(play!.y + play!.height).toBeLessThanOrEqual(390 - 21);
    await page.getByRole('button', { name: 'More', exact: true }).click();
    await page.getByRole('button', { name: /Filmstrip/ }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => {
      for (const key of ['--safe-left', '--safe-right', '--safe-bottom']) document.documentElement.style.removeProperty(key);
      delete (window as any).slideshowImageBeforeRotation;
    });

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
