import { expect, test } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  addMarkerToMedia,
  addMediaToBoard,
  createBoard,
  createProject,
  getBoard,
  getMarkers,
  goToBrowse,
  listMedia,
  listTrash,
  openMediaFromBrowse,
  openToolWithPendingInput,
  seedPendingToolInput,
  TEST_I2I_TOOL_ID,
  trashMedia,
  uploadMediaViaUI,
  waitFor,
  waitForGeneratedFromSource,
  waitForShell,
  submitGeneration,
} from '../helpers/app';

const fixturePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../public/logo.png');

async function uniqueUploadFixture(testInfo: { outputPath: (...segments: string[]) => string }) {
  const bytes = await readFile(fixturePath);
  const target = testInfo.outputPath(`upload-${Date.now()}-${Math.random().toString(16).slice(2)}.png`);
  await writeFile(target, Buffer.concat([bytes, Buffer.from(`\nacceptance-${Date.now()}`)]));
  return target;
}

test.describe('upload import acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('uploaded image appears in browse, opens, and survives reload', async ({ page }, testInfo) => {
    const uploaded = await uploadMediaViaUI(page, await uniqueUploadFixture(testInfo));

    await waitFor(async () => {
      const media = await listMedia(page, { page: 1, page_size: 50, is_generated: false });
      return media.some((item) => item.id === uploaded.id) ? media : null;
    }, 30000);

    await openMediaFromBrowse(page, uploaded.id);
    await goToBrowse(page);
    await page.reload();
    await expect(page.getByTestId(`media-grid-item-${uploaded.id}`)).toBeVisible({ timeout: 30000 });
  });

  test('uploaded image can be marked, boarded, and trashed', async ({ page }, testInfo) => {
    const uploaded = await uploadMediaViaUI(page, await uniqueUploadFixture(testInfo));
    const marker = (await getMarkers(page))[0];
    const board = await createBoard(page, 'Acceptance Upload Board');

    await addMarkerToMedia(page, uploaded.id, marker.id);
    const marked = await listMedia(page, {
      page: 1,
      page_size: 50,
      marker_ids: marker.id,
      is_generated: false,
    });
    expect(marked.some((item) => item.id === uploaded.id)).toBe(true);

    await addMediaToBoard(page, board.id, [uploaded.id]);
    const loadedBoard = await getBoard(page, board.id);
    expect(loadedBoard.sections.some((section) => section.items.some((item) => item.id === uploaded.id))).toBe(true);

    await trashMedia(page, uploaded.id);
    const trashed = await listTrash(page, { page: 1, page_size: 50 });
    expect(trashed.some((item) => item.id === uploaded.id)).toBe(true);
  });

  test('uploaded image can be project-scoped at upload time', async ({ page }, testInfo) => {
    const project = await createProject(page, 'Acceptance Upload Project');
    const uploaded = await uploadMediaViaUI(page, await uniqueUploadFixture(testInfo), project.id);

    const projectMedia = await listMedia(page, {
      page: 1,
      page_size: 50,
      project_id: project.id,
      is_generated: false,
    });
    expect(projectMedia.some((item) => item.id === uploaded.id)).toBe(true);

    await page.goto(`/projects/${project.id}/assets`);
    await expect(page.getByTestId(`media-grid-item-${uploaded.id}`)).toBeVisible({ timeout: 30000 });
  });

  test('uploaded image can be handed to image-to-image as a source input', async ({ page }, testInfo) => {
    const uploaded = await uploadMediaViaUI(page, await uniqueUploadFixture(testInfo));
    const prompt = `acceptance uploaded handoff ${Date.now()}`;

    await seedPendingToolInput(page, TEST_I2I_TOOL_ID, [uploaded.id]);
    await openToolWithPendingInput(page, TEST_I2I_TOOL_ID);
    await submitGeneration(page, prompt);

    const outputs = await waitForGeneratedFromSource(page, TEST_I2I_TOOL_ID, [uploaded.id]);
    expect(outputs[0].generation_metadata).toContain(String(uploaded.id));
  });
});
