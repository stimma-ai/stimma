import { expect, test } from '../helpers/testbed';
import {
  addMediaToCollection,
  createCollection,
  createProject,
  expectContext,
  generateMedia,
  getCollection,
  listMedia,
  waitFor,
  waitForShell,
} from '../helpers/app';

test.describe('projects acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('project pages browse project-scoped media and collections', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Core Project');
    const prompt = `acceptance project browse ${Date.now()}`;
    const media = await generateMedia(page, prompt, project.id);
    const collection = await createCollection(page, 'Acceptance Project Collection', project.id);

    await addMediaToCollection(page, collection.id, [media.id]);

    await waitFor(async () => {
      const projectMedia = await listMedia(page, {
        page: 1,
        page_size: 20,
        prompt_query: prompt,
        project_id: project.id,
      });
      return projectMedia.some((item) => item.id === media.id) ? projectMedia : null;
    }, 30000);

    const loadedCollection = await getCollection(page, collection.id);
    expect(loadedCollection.sections.some((section) => section.items.some((item) => item.id === media.id))).toBe(true);

    await page.goto(`/projects/${project.id}/assets`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
    await expectContext(page, project.name);

    await page.goto(`/projects/${project.id}/collections`);
    await expect(page.getByText('Acceptance Project Collection').first()).toBeVisible({ timeout: 30000 });
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
