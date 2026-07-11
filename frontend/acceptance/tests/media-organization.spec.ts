import { expect, test } from '@playwright/test';
import {
  addMarkerToMedia,
  addMediaToBoard,
  bulkMarkerOperation,
  bulkRestoreMedia,
  bulkTrashMedia,
  createBoard,
  generateMedia,
  goToBrowse,
  getBoard,
  getMarkers,
  listMedia,
  listTrash,
  removeMarkerFromMedia,
  removeMediaFromBoardSection,
  restoreMedia,
  setBatchSize,
  submitGeneration,
  waitForGeneratedMedia,
  trashMedia,
  waitFor,
  waitForShell,
  openTool,
  openMediaFromBrowse,
  TEST_T2I_TOOL_ID,
} from '../helpers/app';

test.describe('media organization acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('generated media can be marked and filtered', async ({ page }) => {
    const prompt = `acceptance marker filter ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const markers = await getMarkers(page);
    const marker = markers.find((item) => item.name === 'favorite') || markers[0];
    expect(marker).toBeTruthy();

    await addMarkerToMedia(page, media.id, marker.id);

    await waitFor(async () => {
      const included = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        marker_ids: marker.id,
      });
      return included.some((item) => item.id === media.id) ? included : null;
    }, 30000);

    const excluded = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      excluded_marker_ids: marker.id,
    });
    expect(excluded.some((item) => item.id === media.id)).toBe(false);
  });

  test('marker can be removed from generated media', async ({ page }) => {
    const prompt = `acceptance marker remove ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const marker = (await getMarkers(page))[0];

    await addMarkerToMedia(page, media.id, marker.id);
    await waitFor(async () => {
      const marked = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        marker_ids: marker.id,
      });
      return marked.some((item) => item.id === media.id) ? marked : null;
    }, 30000);

    await removeMarkerFromMedia(page, media.id, marker.id);
    await waitFor(async () => {
      const marked = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        marker_ids: marker.id,
      });
      return marked.some((item) => item.id === media.id) ? null : marked;
    }, 30000);
  });

  test('multiple generated media can be bulk-marked and filtered', async ({ page }) => {
    const promptA = `acceptance bulk marker A ${Date.now()}`;
    const promptB = `acceptance bulk marker B ${Date.now()}`;
    const first = await generateMedia(page, promptA);
    const second = await generateMedia(page, promptB);
    const marker = (await getMarkers(page))[0];

    await bulkMarkerOperation(page, [first.id, second.id], marker.id, true);

    await waitFor(async () => {
      const marked = await listMedia(page, {
        page: 1,
        page_size: 20,
        marker_ids: marker.id,
      });
      const ids = new Set(marked.map((item) => item.id));
      return ids.has(first.id) && ids.has(second.id) ? marked : null;
    }, 30000);
  });

  test('tool include and exclude filters recognize generated media', async ({ page }) => {
    const prompt = `acceptance tool filter ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    const included = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      tool_ids: TEST_T2I_TOOL_ID,
    });
    expect(included.some((item) => item.id === media.id)).toBe(true);

    const excluded = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      excluded_tool_ids: TEST_T2I_TOOL_ID,
    });
    expect(excluded.some((item) => item.id === media.id)).toBe(false);
  });

  test('prompt search finds generated media', async ({ page }) => {
    const prompt = `acceptance prompt search ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    const results = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
    });
    expect(results.some((item) => item.id === media.id)).toBe(true);
  });

  test('generated-only filter includes generated media', async ({ page }) => {
    const prompt = `acceptance generated filter ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    const results = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      is_generated: true,
    });
    expect(results.some((item) => item.id === media.id)).toBe(true);
  });

  test('non-generated filter excludes generated media', async ({ page }) => {
    const prompt = `acceptance non generated filter ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    const results = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      is_generated: false,
    });
    expect(results.some((item) => item.id === media.id)).toBe(false);
  });

  test('image type and medium resolution filters include fake generated media', async ({ page }) => {
    const prompt = `acceptance image resolution filter ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    const imageResults = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      media_types: 'images',
    });
    expect(imageResults.some((item) => item.id === media.id)).toBe(true);

    const mediumResults = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: prompt,
      resolutions: 'medium',
    });
    expect(mediumResults.some((item) => item.id === media.id)).toBe(true);
  });

  test('newest sort returns newer generated media first', async ({ page }) => {
    const stamp = Date.now();
    const older = await generateMedia(page, `acceptance newest older ${stamp}`);
    const newer = await generateMedia(page, `acceptance newest newer ${stamp}`);

    const results = await listMedia(page, {
      page: 1,
      page_size: 20,
      prompt_query: `acceptance newest`,
      sort_by: 'created_desc',
    });
    const ids = results.map((item) => item.id);
    expect(ids.indexOf(newer.id)).toBeGreaterThanOrEqual(0);
    expect(ids.indexOf(older.id)).toBeGreaterThanOrEqual(0);
    expect(ids.indexOf(newer.id)).toBeLessThan(ids.indexOf(older.id));
  });

  test('generated media can be opened from browse', async ({ page }) => {
    const prompt = `acceptance browse open ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    await openMediaFromBrowse(page, media.id);
  });

  test('batch generation creates multiple media items', async ({ page }) => {
    const prompt = `acceptance batch generation ${Date.now()}`;
    await openTool(page);
    await setBatchSize(page, 2);
    await submitGeneration(page, prompt);

    const generated = await waitForGeneratedMedia(page, { prompt, expectedCount: 2 });
    expect(generated.length).toBeGreaterThanOrEqual(2);
  });

  test('generated media can be trashed and restored', async ({ page }) => {
    const prompt = `acceptance trash restore ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    await trashMedia(page, media.id);

    await waitFor(async () => {
      const trashed = await listTrash(page, { page: 1, page_size: 20, prompt_query: prompt });
      return trashed.some((item) => item.id === media.id) ? trashed : null;
    }, 30000);

    const browseAfterTrash = await listMedia(page, { page: 1, page_size: 20, prompt_query: prompt });
    expect(browseAfterTrash.some((item) => item.id === media.id)).toBe(false);

    await page.goto('/trash');
    await waitForShell(page);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });

    await restoreMedia(page, media.id);
    await waitFor(async () => {
      const restored = await listMedia(page, { page: 1, page_size: 20, prompt_query: prompt });
      return restored.some((item) => item.id === media.id) ? restored : null;
    }, 30000);
  });

  test('multiple generated media can be bulk-trashed and restored', async ({ page }) => {
    const promptA = `acceptance bulk trash A ${Date.now()}`;
    const promptB = `acceptance bulk trash B ${Date.now()}`;
    const first = await generateMedia(page, promptA);
    const second = await generateMedia(page, promptB);

    await bulkTrashMedia(page, [first.id, second.id]);

    await waitFor(async () => {
      const trashed = await listTrash(page, { page: 1, page_size: 50 });
      const ids = new Set(trashed.map((item) => item.id));
      return ids.has(first.id) && ids.has(second.id) ? trashed : null;
    }, 30000);

    await bulkRestoreMedia(page, [first.id, second.id]);

    await waitFor(async () => {
      const restoredA = await listMedia(page, { page: 1, page_size: 20, prompt_query: promptA });
      const restoredB = await listMedia(page, { page: 1, page_size: 20, prompt_query: promptB });
      return restoredA.some((item) => item.id === first.id) &&
        restoredB.some((item) => item.id === second.id)
        ? [...restoredA, ...restoredB]
        : null;
    }, 30000);
  });

  test('boards can collect generated media', async ({ page }) => {
    const prompt = `acceptance board media ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const board = await createBoard(page, 'Acceptance Board');

    await addMediaToBoard(page, board.id, [media.id]);

    await waitFor(async () => {
      const loaded = await getBoard(page, board.id);
      const hasMedia = loaded.sections.some((section) => (
        section.items.some((item) => item.id === media.id)
      ));
      return hasMedia ? loaded : null;
    }, 30000);

    await page.goto(`/boards/${board.id}`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  });

  test('media can be removed from a board', async ({ page }) => {
    const prompt = `acceptance board remove ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const board = await createBoard(page, 'Acceptance Remove Board');

    await addMediaToBoard(page, board.id, [media.id]);
    const loaded = await waitFor(async () => {
      const current = await getBoard(page, board.id);
      const section = current.sections.find((item) => item.items.some((entry) => entry.id === media.id));
      return section ? { current, section } : null;
    }, 30000);

    await removeMediaFromBoardSection(page, loaded.section.id, media.id);

    await waitFor(async () => {
      const current = await getBoard(page, board.id);
      const stillPresent = current.sections.some((section) => section.items.some((item) => item.id === media.id));
      return stillPresent ? null : current;
    }, 30000);
  });

  test('board detail survives reload with generated media visible', async ({ page }) => {
    const prompt = `acceptance board reload ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const board = await createBoard(page, 'Acceptance Reload Board');
    await addMediaToBoard(page, board.id, [media.id]);

    await page.goto(`/boards/${board.id}`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
    await page.reload();
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  });
});
