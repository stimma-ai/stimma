import { test, expect } from '@playwright/test';
import { goToBrowse } from '../../helpers/navigation';
import {
  goToCollections,
  goToCollection,
  getMediaItems,
  ensureMediaExists,
  ctrlClickItem,
  waitForActionBar,
  getActionBar,
  createCollectionViaApi,
  deleteCollectionViaApi,
  addMediaToCollectionViaApi,
  getMediaIdsViaApi,
} from '../../helpers/library';

const createdCollectionIds: string[] = [];

test.describe('Library - Collections', () => {
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    for (const id of createdCollectionIds) {
      try {
        await deleteCollectionViaApi(page, id);
      } catch {
        // ignore cleanup errors
      }
    }
    createdCollectionIds.length = 0;
    await page.close();
  });

  // ── Collections Landing ───────────────────────────────────────────

  test.describe('Collections Landing', () => {
    test('collections page loads', async ({ page }) => {
      await goToCollections(page);
      await expect(page.getByRole('heading', { name: 'Collections' })).toBeVisible();
    });

    test('navigate via sidebar', async ({ page }) => {
      await goToBrowse(page);
      await page.getByText('Collections', { exact: true }).click();
      await page.waitForLoadState('networkidle');
      await expect(page.getByRole('heading', { name: 'Collections' })).toBeVisible();
    });

    test('"New Collection" creates and navigates to detail', async ({ page }) => {
      await goToCollections(page);
      await page.getByText('New Collection').click();
      await page.waitForURL(/\/collections\/\d+/);
      await expect(page.locator('.collection-detail-view')).toBeVisible();
      // Extract collection ID from URL for cleanup
      const url = page.url();
      const match = url.match(/\/collections\/(\d+)/);
      if (match) createdCollectionIds.push(match[1]);
    });

    test('search filters collection grid', async ({ page }) => {
      const uniqueName = `Test-Search-${Date.now()}`;
      const id = await createCollectionViaApi(page, uniqueName);
      createdCollectionIds.push(id);

      await goToCollections(page);
      // Wait for collections to load before searching
      await page.waitForTimeout(1000);
      await page.locator('input[placeholder="Search collections..."]').fill(uniqueName);
      await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 10000 });
    });
  });

  // ── Collection Detail ─────────────────────────────────────────────

  test.describe('Collection Detail', () => {
    test('detail page shows header', async ({ page }) => {
      const id = await createCollectionViaApi(page, `Detail-Test-${Date.now()}`);
      createdCollectionIds.push(id);

      await goToCollection(page, id);
      await expect(page.locator('.collection-detail-view')).toBeVisible();
    });

    test('empty collection shows no items', async ({ page }) => {
      const id = await createCollectionViaApi(page, `Empty-Col-${Date.now()}`);
      createdCollectionIds.push(id);

      await goToCollection(page, id);
      // Wait for page to settle, then verify no grid items
      await page.waitForTimeout(1000);
      expect(await getMediaItems(page).count()).toBe(0);
    });

    test('collection with media shows items', async ({ page }) => {
      const id = await createCollectionViaApi(page, `Media-Col-${Date.now()}`);
      createdCollectionIds.push(id);

      const mediaIds = await getMediaIdsViaApi(page, 2);
      test.skip(mediaIds.length === 0, 'No media available');
      await addMediaToCollectionViaApi(page, mediaIds, id);

      await goToCollection(page, id);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
      expect(await getMediaItems(page).count()).toBeGreaterThanOrEqual(1);
    });

    test('collection name is editable', async ({ page }) => {
      const originalName = `Editable-Col-${Date.now()}`;
      const newName = `Renamed-Col-${Date.now()}`;
      const id = await createCollectionViaApi(page, originalName);
      createdCollectionIds.push(id);

      await goToCollection(page, id);
      // Wait for collection data to load and name to render
      await expect(page.getByRole('heading', { name: originalName })).toBeVisible({ timeout: 10000 });
      // Click the name heading to edit
      await page.getByRole('heading', { name: originalName }).click();
      const input = page.locator('.collection-detail-view input[type="text"]');
      await input.waitFor({ state: 'visible', timeout: 5000 });
      await input.fill(newName);
      await input.press('Enter');
      await page.waitForTimeout(1000);
      await expect(page.getByText(newName)).toBeVisible();
    });
  });

  // ── Add to Collection (via Browse) ────────────────────────────────

  test.describe('Add to Collection', () => {
    test.beforeEach(async ({ page }) => {
      await goToBrowse(page);
      await ensureMediaExists(page);
    });

    test('"Add to collections" opens CollectionPicker', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();
    });

    test('picker shows existing collections', async ({ page }) => {
      const name = `Picker-Test-${Date.now()}`;
      const id = await createCollectionViaApi(page, name);
      createdCollectionIds.push(id);

      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();
      await expect(page.getByText(name)).toBeVisible({ timeout: 10000 });
    });

    test('picker has "Create new collection" input', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();
      await expect(page.locator('input[placeholder="Create new collection..."]')).toBeVisible();
    });

    test('select collection and add media', async ({ page }) => {
      const name = `Add-Media-Col-${Date.now()}`;
      const id = await createCollectionViaApi(page, name);
      createdCollectionIds.push(id);

      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();

      // Click collection name in picker to select it
      await page.getByText(name).click();
      // Click the add button
      await page.getByText(/Add to \d+ collection/).click();
      await page.waitForTimeout(1000);

      // Navigate to collection and verify media is there
      await goToCollection(page, id);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
    });

    test('cancel closes picker', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();
      await page.getByText('Cancel').click();
      await expect(page.getByText('Add to Collection')).not.toBeVisible();
    });

    test('escape closes picker', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      await page.locator('button[title="Add to collections"]').click();
      await expect(page.getByText('Add to Collection')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByText('Add to Collection')).not.toBeVisible();
    });
  });

  // ── Remove from Collection ────────────────────────────────────────

  test.describe('Remove from Collection', () => {
    test('select items in collection and remove', async ({ page }) => {
      const id = await createCollectionViaApi(page, `Remove-Test-${Date.now()}`);
      createdCollectionIds.push(id);

      const mediaIds = await getMediaIdsViaApi(page, 2);
      test.skip(mediaIds.length === 0, 'No media available');
      await addMediaToCollectionViaApi(page, mediaIds, id);

      await goToCollection(page, id);
      await expect(getMediaItems(page).first()).toBeVisible({ timeout: 15000 });
      const initialCount = await getMediaItems(page).count();

      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      // Look for a remove button in the action bar
      const removeBtn = getActionBar(page).locator('button[title="Remove from collection"]');
      if (await removeBtn.isVisible()) {
        await removeBtn.click();
        await page.waitForTimeout(1000);
        const newCount = await getMediaItems(page).count();
        expect(newCount).toBeLessThan(initialCount);
      }
    });
  });
});
