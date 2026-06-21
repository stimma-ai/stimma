import { expect, test } from '@playwright/test';
import {
  createProject,
  openTool,
  submitGeneration,
  waitForGeneratedMedia,
  waitForShell,
} from '../helpers/app';

test.describe('release acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('fresh app loads tools and completes a fake text-to-image generation', async ({ page }) => {
    await page.goto('/tools');
    await expect(page.getByText('Test Text-to-Image')).toBeVisible({ timeout: 30000 });

    await openTool(page);
    await submitGeneration(page, 'acceptance test image');

    const media = await waitForGeneratedMedia(page, { prompt: 'acceptance test image' });
    expect(media.length).toBeGreaterThan(0);

    await page.goto('/browse');
    await waitForShell(page);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  });

  test('project-scoped tool generation creates project media', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Project');

    await page.goto(`/projects/${project.id}/tools`);
    await expect(page.getByText('Test Text-to-Image')).toBeVisible({ timeout: 30000 });

    await openTool(page, project.id);
    await submitGeneration(page, 'acceptance project scoped image');

    const projectMedia = await waitForGeneratedMedia(page, {
      prompt: 'acceptance project scoped image',
      projectId: project.id,
    });
    expect(projectMedia.length).toBeGreaterThan(0);

    await page.goto(`/projects/${project.id}/assets`);
    await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  });
});
