import { test, expect } from '@playwright/test';
import { goToBrowse, goToTool, goToTools } from '../helpers/navigation';
import { submitGeneration, waitForJobComplete, getResultTiles } from '../helpers/generation';
import { describeWithTestProvider } from '../helpers/fixtures';

test.describe('Smoke Tests', () => {
  test('app loads and browse view is accessible', async ({ page }) => {
    await goToBrowse(page);
    await expect(page.getByRole('button', { name: 'All Assets' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Tools' })).toBeVisible();
  });
});

describeWithTestProvider('Smoke Tests (Test Provider)', () => {
  test('tools listing page shows test tool', async ({ page }) => {
    await goToTools(page);
    await expect(page.getByText('Test Text-to-Image')).toBeVisible({ timeout: 10000 });
  });

  test('navigate to test tool, parameters render', async ({ page }) => {
    await goToTool(page);
    await expect(page.locator('.prompt-textarea')).toBeVisible();
    await expect(page.getByRole('button', { name: /^Run/ })).toBeVisible();
  });

  test('submit generation, job completes, result tile appears', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a red cat sitting on a blue couch');
    await waitForJobComplete(page);
    const tiles = await getResultTiles(page);
    await expect(tiles.first()).toBeVisible();
  });

  test('result tile shows thumbnail image with valid src', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a green tree in a field');
    await waitForJobComplete(page);
    const tiles = await getResultTiles(page);
    const img = tiles.first();
    await expect(img).toBeVisible();
    const src = await img.getAttribute('src');
    expect(src).toBeTruthy();
  });
});
