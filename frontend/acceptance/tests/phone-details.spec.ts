import { mkdir } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { createBoard, createChat, TEST_T2I_TOOL_ID } from '../helpers/app';
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

async function audit(page: Page, key: string) {
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
  const hits = await auditHitTargets(page);
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
  test('tool view fits a phone', async ({ page }) => {
    await page.goto(`/tools/${TEST_T2I_TOOL_ID}`);
    await settleAnyViewport(page);
    await expect(page.getByRole('button', { name: /^Run/ }).first()).toBeVisible({ timeout: 30000 });
    await expect(page.locator('.compact-tab-bar')).toBeVisible();
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
    await expect(page.locator('.compact-tab-bar')).toBeVisible();
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

  test('settings opens as a full-screen list from the avatar', async ({ page }) => {
    await page.goto('/home');
    await settleAnyViewport(page);
    await page.getByRole('button', { name: 'Account and settings' }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
    await audit(page, 'settings');
    await page.getByRole('button', { name: 'Markers' }).click();
    await expect(page.getByRole('heading', { name: 'Markers' }).first()).toBeVisible();
    await page.screenshot({ path: 'acceptance/phone-shots/detail-settings-section.png' });
  });
});
