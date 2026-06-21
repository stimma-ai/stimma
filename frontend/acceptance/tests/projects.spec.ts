import { expect, test } from '@playwright/test';
import {
  addMediaToBoard,
  createBoard,
  createProject,
  generateMedia,
  getBoard,
  listMedia,
  waitFor,
  waitForShell,
} from '../helpers/app';

test.describe('projects acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('project pages browse project-scoped media and boards', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Core Project');
    const prompt = `acceptance project browse ${Date.now()}`;
    const media = await generateMedia(page, prompt, project.id);
    const board = await createBoard(page, 'Acceptance Project Board', project.id);

    await addMediaToBoard(page, board.id, [media.id]);

    await waitFor(async () => {
      const projectMedia = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        project_id: project.id,
      });
      return projectMedia.some((item) => item.id === media.id) ? projectMedia : null;
    }, 30000);

    const loadedBoard = await getBoard(page, board.id);
    expect(loadedBoard.sections.some((section) => section.items.some((item) => item.id === media.id))).toBe(true);

    await page.goto(`/projects/${project.id}/assets`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });

    await page.goto(`/projects/${project.id}/boards`);
    await expect(page.getByText('Acceptance Project Board').first()).toBeVisible({ timeout: 30000 });
  });

  test('project tool routes preserve project scope after reload', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Reload Project');
    const prompt = `acceptance project reload ${Date.now()}`;

    const media = await generateMedia(page, prompt, project.id);
    await page.reload();
    await expect(page.url()).toContain(`project_id=${project.id}`);

    await waitFor(async () => {
      const projectMedia = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        project_id: project.id,
      });
      return projectMedia.some((item) => item.id === media.id) ? projectMedia : null;
    }, 30000);

    await page.goto(`/projects/${project.id}/assets`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  });
});
