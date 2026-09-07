import { mkdir } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { createBoard, createChat, promptInput, TEST_T2I_TOOL_ID, waitForGeneratedMedia } from '../helpers/app';
import { auditHitTargets, auditHorizontalOverflow, expectNoOverflow, settleAnyViewport } from '../helpers/viewport';

/**
 * Phone lane, detail screens: a tool, a chat, a board, a flow, the settings
 * sheet. Same two rules as the hub audit (no horizontal overflow, no visible
 * sub-44px control), same ratchet. Entities are created through the API or
 * the app's own "New" actions so the screens carry real content.
 */

const KNOWN_BAD: Record<string, { overflow?: boolean; hitTargets?: boolean }> = {
  tool: { hitTargets: true },
  chat: { hitTargets: true },
  board: { hitTargets: true },
  flow: { hitTargets: true },
  settings: { hitTargets: true },
};

async function audit(page: Page, key: string, hitRoot = 'body') {
  await mkdir('acceptance/phone-shots', { recursive: true });
  await page.screenshot({ path: `acceptance/phone-shots/detail-${key}.png`, fullPage: false });
  const known = KNOWN_BAD[key] ?? {};
  const overflow = await auditHorizontalOverflow(page);
  if (known.overflow) {
    if (overflow.docWidth > overflow.viewportWidth + 1 || overflow.offenders.length) {
      console.warn(`[phone] ${key} overflows (known): ${overflow.offenders.join(', ')}`);
    } else {
      console.warn(`[phone] ${key} no longer overflows — remove it from KNOWN_BAD.overflow`);
    }
  } else {
    expectNoOverflow(overflow, key);
  }
  const hits = await auditHitTargets(page, 44, hitRoot);
  if (known.hitTargets) {
    if (hits.small.length) {
      console.warn(`[phone] ${key} has ${hits.small.length}/${hits.total} sub-44px targets (known): ${hits.small.slice(0, 8).map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`);
    } else {
      console.warn(`[phone] ${key} hit targets are clean — remove it from KNOWN_BAD.hitTargets`);
    }
  } else {
    expect(hits.small, `${key}: interactive elements under 44px: ${hits.small.map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`).toHaveLength(0);
  }
}

test.describe('phone lane: detail screens', () => {
  test('image editor fits a phone', async ({ page }) => {
    test.setTimeout(150000);
    // An image to edit: one run through the compact tool view.
    await page.goto(`/tools/${TEST_T2I_TOOL_ID}`);
    await settleAnyViewport(page);
    await promptInput(page).fill(`phone editor ${Date.now()}`);
    // A fresh sandbox raises the readiness panel once its checks land, which
    // can be after settle returns on a slow runner; it would sit over Run.
    const readiness = page.getByTestId('readiness-panel');
    if (await readiness.isVisible({ timeout: 3000 }).catch(() => false)) {
      await page.getByTestId('readiness-dismiss').click({ force: true });
      await expect(readiness).toBeHidden({ timeout: 10000 });
    }
    const run = page.locator('#compact-header-actions').getByTestId('tool-run-button');
    await expect(run).toBeEnabled({ timeout: 15000 });
    await run.click({ timeout: 30000 });
    const [media] = await waitForGeneratedMedia(page, {});
    expect(media.asset_id, 'generated media carries its asset id').toBeTruthy();

    // Resting: header, drawer with the stack, family bar.
    await page.goto(`/edit-image/${media.asset_id}`);
    await settleAnyViewport(page);
    await expect(page.locator('.editor-compact-header')).toBeVisible({ timeout: 30000 });
    await expect(page.locator('#editor-drawer-body')).toContainText('Original image', { timeout: 30000 });
    const bar = page.locator('[role="toolbar"][aria-label="Editor families"]');
    await expect(bar).toBeVisible();
    await audit(page, 'editor');

    // Crop: ratio chips, straighten, verbs.
    await bar.getByRole('button', { name: 'Crop', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Flip H' })).toBeVisible();
    await audit(page, 'editor-crop');

    // Adjust: a Light step and its sliders in the drawer.
    await bar.getByRole('button', { name: 'Adjust', exact: true }).click();
    await page.getByRole('button', { name: 'Light', exact: true }).click();
    await expect(page.locator('#editor-drawer-body input[type="range"]').first()).toBeVisible({ timeout: 15000 });
    await audit(page, 'editor-adjust');

    // Generate: the sub-tools, the brush strip over the matte, Run.
    await bar.getByRole('button', { name: 'Generate', exact: true }).click();
    await expect(page.getByRole('button', { name: /^Run/ }).first()).toBeVisible();
    await audit(page, 'editor-generate');

    // Selection: the glass button opens the tool sheet.
    await bar.getByRole('button', { name: 'Edits', exact: true }).click();
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await expect(page.locator('[data-sheet-layer]').getByRole('button', { name: 'Lasso', exact: true })).toBeVisible();
    await audit(page, 'editor-select-sheet', '[data-sheet-layer]');
    await page.keyboard.press('Escape');

    // The document sheet: Output, Info, Compare, Save as new asset, Revert.
    await page.getByRole('button', { name: 'Document options' }).click();
    await expect(page.locator('[data-sheet-layer]').getByRole('button', { name: 'Revert to last save' })).toBeVisible();
    await audit(page, 'editor-document-sheet', '[data-sheet-layer]');
    await page.keyboard.press('Escape');
  });


  test('tool view fits a phone', async ({ page }) => {
    await page.goto(`/tools/${TEST_T2I_TOOL_ID}`);
    await settleAnyViewport(page);
    await expect(page.getByRole('button', { name: /^Run/ }).first()).toBeVisible({ timeout: 30000 });
    await expect(page.locator('.compact-header')).toBeVisible();
    await audit(page, 'tool');
  });

  test('chat fits a phone', async ({ page }) => {
    await page.goto('/chats');
    await settleAnyViewport(page);
    const chat = await createChat(page, 'Phone lane chat');
    await page.goto(`/chat/${chat.id}`);
    await settleAnyViewport(page);
    await expect(page.locator('.compact-header h1')).toHaveText('Phone lane chat', { timeout: 15000 });
    await audit(page, 'chat');
  });

  test('board detail fits a phone', async ({ page }) => {
    await page.goto('/boards');
    await settleAnyViewport(page);
    const board = await createBoard(page, 'Phone lane board');
    await page.goto(`/boards/${board.id}`);
    await settleAnyViewport(page);
    await expect(page.locator('.compact-header')).toBeVisible();
    await audit(page, 'board');
  });

  test('flow fits a phone', async ({ page }) => {
    await page.goto('/flows');
    await settleAnyViewport(page);
    await page.getByRole('button', { name: 'New' }).first().click();
    await page.waitForURL(/\/flows\/[^/]+$/, { timeout: 15000 });
    await settleAnyViewport(page);
    await audit(page, 'flow');
  });

  test('settings opens as a full-screen list from the drawer', async ({ page }) => {
    await page.goto('/home');
    await settleAnyViewport(page);
    await page.getByRole('button', { name: 'Menu' }).click();
    await page.locator('.navigation-sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
    await audit(page, 'settings');
  });

  // Every settings section, one by one: no horizontal overflow, ever. Hit
  // targets are reported, not enforced, until the settings kit pass.
  const SECTIONS = ['Folders', 'Markers', 'Prompt Variables', 'Agent', 'Stimma Account', 'Stimma Server', 'Generation Tools', 'Chat Models', 'Preferences', 'Profiles', 'Background Work', 'Privacy', 'About'];
  for (const section of SECTIONS) {
    test(`settings › ${section} fits a phone`, async ({ page }) => {
      await page.goto('/home');
      await settleAnyViewport(page);
      // Desktop browser emulation otherwise reports zero iPhone safe insets.
      await page.evaluate(() => {
        document.documentElement.style.setProperty('--safe-top', '59px');
        document.documentElement.style.setProperty('--safe-bottom', '34px');
      });
      await page.getByRole('button', { name: 'Menu' }).click();
      await page.locator('.navigation-sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
      await page.getByRole('button', { name: section }).first().click();
      await page.waitForTimeout(600);
      const layer = page.locator('[data-modal-layer]').last();
      const heading = await layer.locator('h2').first().boundingBox();
      const close = await layer.getByRole('button', { name: 'Close', exact: true }).boundingBox();
      expect(heading!.y).toBeGreaterThanOrEqual(59);
      expect(close!.y).toBeGreaterThanOrEqual(59);
      const scrollArea = await layer.locator('[data-settings-content]').boundingBox();
      expect(scrollArea!.y + scrollArea!.height).toBeLessThanOrEqual(page.viewportSize()!.height - 34);
      // Scrolling the section must never move the header into the status bar.
      await layer.locator('[data-settings-content]').evaluate(el => { el.scrollTop = el.scrollHeight });
      expect((await layer.getByRole('button', { name: 'Close', exact: true }).boundingBox())!.y).toBeGreaterThanOrEqual(59);
      const slug = section.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      await page.screenshot({ path: `acceptance/phone-shots/settings-${slug}.png` });
      const overflow = await auditHorizontalOverflow(page);
      expectNoOverflow(overflow, `settings/${section}`);
      const hits = await auditHitTargets(page, 44, '[data-modal-layer]');
      if (hits.small.length) console.warn(`[phone] settings/${section}: ${hits.small.length}/${hits.total} sub-44px: ${hits.small.slice(0, 6).map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`);
    });
  }
});
