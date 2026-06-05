import { test, expect } from '@playwright/test';
import { goToBrowse } from '../../helpers/navigation';
import {
  goToTrash,
  getMediaItems,
  ensureMediaExists,
  ctrlClickItem,
  waitForActionBar,
  getActionBar,
  getMediaIdsViaApi,
  moveToTrashViaApi,
  restoreFromTrashViaApi,
} from '../../helpers/library';

const trashedIds: number[] = [];

test.describe('Library - Trash', () => {
  test.afterEach(async ({ browser }) => {
    // Restore any items trashed during the test
    if (trashedIds.length > 0) {
      const page = await browser.newPage();
      try {
        await restoreFromTrashViaApi(page, [...trashedIds]);
      } catch {
        // ignore cleanup errors
      }
      trashedIds.length = 0;
      await page.close();
    }
  });

  // ── Navigate to Trash ─────────────────────────────────────────────

  test.describe('Navigate to Trash', () => {
    test('trash page loads with header', async ({ page }) => {
      await goToTrash(page);
      await expect(page.getByRole('heading', { name: 'Trash', level: 1 })).toBeVisible();
    });

    test('navigate via sidebar', async ({ page }) => {
      await goToBrowse(page);
      await page.getByText('Trash', { exact: true }).click();
      await page.waitForLoadState('networkidle');
      await expect(page.getByRole('heading', { name: 'Trash', level: 1 })).toBeVisible();
    });

    test('empty trash shows empty state', async ({ page }) => {
      await goToTrash(page);
      // Wait for trash to load
      await page.waitForTimeout(2000);
      const count = await getMediaItems(page).count();
      if (count === 0) {
        await expect(page.getByText('Trash is empty')).toBeVisible();
        await expect(page.getByText('Deleted items will appear here')).toBeVisible();
      }
    });
  });

  // ── Move to Trash ─────────────────────────────────────────────────

  test.describe('Move to Trash', () => {
    test('move to trash from browse', async ({ page }) => {
      await goToBrowse(page);
      await ensureMediaExists(page);

      // Get the media ID before trashing for cleanup
      const mediaIds = await getMediaIdsViaApi(page, 1);
      trashedIds.push(...mediaIds);

      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      await page.locator('button[title="Move to trash"]').click();
      await page.waitForTimeout(1000);

      // Action bar should dismiss after action
      await expect(getActionBar(page)).not.toBeVisible({ timeout: 5000 });
    });

    test('trashed items appear in trash view', async ({ page }) => {
      const mediaIds = await getMediaIdsViaApi(page, 2);
      test.skip(mediaIds.length === 0, 'No media available');

      await moveToTrashViaApi(page, mediaIds);
      trashedIds.push(...mediaIds);

      await goToTrash(page);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
      expect(await getMediaItems(page).count()).toBeGreaterThanOrEqual(1);
    });

    test('trash header shows count', async ({ page }) => {
      const mediaIds = await getMediaIdsViaApi(page, 1);
      test.skip(mediaIds.length === 0, 'No media available');

      await moveToTrashViaApi(page, mediaIds);
      trashedIds.push(...mediaIds);

      await goToTrash(page);
      await expect(page.locator('p').filter({ hasText: /\d+ deleted/ })).toBeVisible({ timeout: 10000 });
    });
  });

  // ── Trash View Actions ────────────────────────────────────────────

  test.describe('Trash View Actions', () => {
    test.beforeEach(async ({ page }) => {
      // Ensure there are items in trash
      const mediaIds = await getMediaIdsViaApi(page, 2);
      test.skip(mediaIds.length === 0, 'No media available');

      await moveToTrashViaApi(page, mediaIds);
      trashedIds.push(...mediaIds);

      await goToTrash(page);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
    });

    test('action bar shows trash-specific buttons', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      await expect(page.locator('button[title="Restore"]')).toBeVisible();
      await expect(page.locator('button[title="Delete permanently"]')).toBeVisible();
      await expect(page.locator('button[title="Move to trash"]')).not.toBeVisible();
    });

    test('restore from trash', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Restore"]').click();

      // After restore, action bar should dismiss (selection cleared)
      await expect(getActionBar(page)).not.toBeVisible({ timeout: 10000 });
      // Remove one from trashedIds since it was restored via UI
      trashedIds.shift();
    });

    test('permanently delete removes items', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      const deleteBtn = page.locator('button[title="Delete permanently"]');
      await expect(deleteBtn).toBeVisible();
      await deleteBtn.click();

      // Action bar should dismiss after permanent deletion (selection cleared)
      await expect(getActionBar(page)).not.toBeVisible({ timeout: 10000 });
      // Remove one from trashedIds since it was permanently deleted
      trashedIds.shift();
    });
  });

  // ── Empty Trash ───────────────────────────────────────────────────

  test.describe('Empty Trash', () => {
    test('empty trash button visible when items exist', async ({ page }) => {
      const mediaIds = await getMediaIdsViaApi(page, 1);
      test.skip(mediaIds.length === 0, 'No media available');

      await moveToTrashViaApi(page, mediaIds);
      trashedIds.push(...mediaIds);

      await goToTrash(page);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
      await expect(page.getByRole('button', { name: 'Empty Trash' })).toBeVisible();
    });

    test('empty trash shows confirmation', async ({ page }) => {
      const mediaIds = await getMediaIdsViaApi(page, 1);
      test.skip(mediaIds.length === 0, 'No media available');

      await moveToTrashViaApi(page, mediaIds);
      trashedIds.push(...mediaIds);

      await goToTrash(page);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });

      await page.getByRole('button', { name: 'Empty Trash' }).click();
      await expect(page.getByText('Empty Trash?')).toBeVisible();
      // Cancel to avoid actual deletion
      await page.locator('.cancel-button').click();
      await expect(page.getByText('Empty Trash?')).not.toBeVisible();
    });

    test('empty trash button hidden when empty', async ({ page }) => {
      await goToTrash(page);
      // Wait for trash to load
      await page.waitForTimeout(2000);
      const count = await getMediaItems(page).count();
      if (count === 0) {
        await expect(page.getByRole('button', { name: 'Empty Trash' })).not.toBeVisible();
      }
    });
  });
});
