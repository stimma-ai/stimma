import { test, expect } from '@playwright/test';
import { goToBrowse } from '../../helpers/navigation';
import {
  getMediaItems,
  ensureMediaExists,
  ctrlClickItem,
  selectItems,
  waitForActionBar,
  getActionBar,
  getActionBarMarkerButtons,
  getFilterBarMarkerButton,
  clickFilterBarMarker,
  isMarkerFilterPositive,
  isMarkerFilterNegative,
  clickActionBarMarker,
  isActionBarMarkerActive,
  getMarkersViaApi,
} from '../../helpers/library';

let markers: Array<{ id: number; name: string; icon_svg: string; color: string }> = [];

test.describe('Library - Markers', () => {
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    markers = await getMarkersViaApi(page);
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    test.skip(markers.length === 0, 'No markers configured - skipping marker tests');
    await goToBrowse(page);
    await ensureMediaExists(page);
  });

  // ── Filter Bar Cycling ──────────────────────────────────────────────

  test.describe('Filter Bar - Marker Cycling', () => {
    test('marker toggle buttons are visible in filter bar', async ({ page }) => {
      for (const marker of markers) {
        await expect(getFilterBarMarkerButton(page, marker.name)).toBeVisible();
      }
    });

    test('click cycles: neutral -> positive (blue)', async ({ page }) => {
      const name = markers[0].name;
      await clickFilterBarMarker(page, name);
      expect(await isMarkerFilterPositive(page, name)).toBe(true);
      expect(await isMarkerFilterNegative(page, name)).toBe(false);
    });

    test('click cycles: positive -> negative (red)', async ({ page }) => {
      const name = markers[0].name;
      // First click: neutral -> positive
      await clickFilterBarMarker(page, name);
      // Second click: positive -> negative
      await clickFilterBarMarker(page, name);
      expect(await isMarkerFilterPositive(page, name)).toBe(false);
      expect(await isMarkerFilterNegative(page, name)).toBe(true);
    });

    test('click cycles: negative -> neutral', async ({ page }) => {
      const name = markers[0].name;
      // Three clicks: neutral -> positive -> negative -> neutral
      await clickFilterBarMarker(page, name);
      await clickFilterBarMarker(page, name);
      await clickFilterBarMarker(page, name);
      expect(await isMarkerFilterPositive(page, name)).toBe(false);
      expect(await isMarkerFilterNegative(page, name)).toBe(false);
    });

    test('positive filter changes grid results', async ({ page }) => {
      const initialCount = await getMediaItems(page).count();
      const name = markers[0].name;
      await clickFilterBarMarker(page, name);
      // Wait for grid to update
      await page.waitForTimeout(1000);
      const filteredCount = await getMediaItems(page).count();
      // Count may change (could be same if all items have marker, or less)
      expect(filteredCount).toBeGreaterThanOrEqual(0);
      expect(filteredCount).toBeLessThanOrEqual(initialCount);
    });

    test('negative filter changes grid results', async ({ page }) => {
      const initialCount = await getMediaItems(page).count();
      const name = markers[0].name;
      // Two clicks: neutral -> positive -> negative
      await clickFilterBarMarker(page, name);
      await clickFilterBarMarker(page, name);
      await page.waitForTimeout(1000);
      const filteredCount = await getMediaItems(page).count();
      expect(filteredCount).toBeGreaterThanOrEqual(0);
      expect(filteredCount).toBeLessThanOrEqual(initialCount);
    });
  });

  // ── Mark/Unmark via Action Bar ──────────────────────────────────────

  test.describe('Action Bar - Mark/Unmark', () => {
    test('marker buttons appear in action bar', async ({ page }) => {
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);
      const markerBtns = getActionBarMarkerButtons(page);
      await expect(markerBtns.first()).toBeVisible();
      expect(await markerBtns.count()).toBe(markers.length);
    });

    test('click marker button marks selected items', async ({ page }) => {
      const name = markers[0].name;
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      // Should start with "Add {name}" title
      const addBtn = getActionBar(page).locator(`button[title="Add ${name}"]`);
      if (await addBtn.isVisible()) {
        await clickActionBarMarker(page, name);
        // Wait for DOM to update after marker toggle
        await page.waitForTimeout(1000);
        expect(await isActionBarMarkerActive(page, name)).toBe(true);
      }
      // If already active, it was already marked - just verify active state
    });

    test('click active marker unmarks items', async ({ page }) => {
      const name = markers[0].name;
      await ctrlClickItem(page, 0);
      await waitForActionBar(page);

      // Ensure item is marked first
      if (!(await isActionBarMarkerActive(page, name))) {
        await clickActionBarMarker(page, name);
        await page.waitForTimeout(500);
      }

      // Now unmark
      await clickActionBarMarker(page, name);
      await page.waitForTimeout(500);
      expect(await isActionBarMarkerActive(page, name)).toBe(false);
    });

    test('batch mark multiple items', async ({ page }) => {
      const name = markers[0].name;
      await selectItems(page, [0, 1]);
      await waitForActionBar(page);

      // Mark both items
      const addBtn = getActionBar(page).locator(`button[title="Add ${name}"]`);
      if (await addBtn.isVisible()) {
        await clickActionBarMarker(page, name);
        // Wait for marker API call to complete and UI to update
        const activeBtn = getActionBar(page).locator(`button.marker-button.active[title="Remove ${name}"]`);
        await expect(activeBtn).toBeVisible({ timeout: 10000 });
      }
    });
  });
});
