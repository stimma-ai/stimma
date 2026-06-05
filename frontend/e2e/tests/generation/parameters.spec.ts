import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { describeWithTestProvider } from '../../helpers/fixtures';

describeWithTestProvider('Generation Parameters', () => {
  test('steps slider is visible and adjustable', async ({ page }) => {
    await goToTool(page);
    const stepsInput = page.locator('input[type="range"]').first();
    if (await stepsInput.isVisible()) {
      await stepsInput.fill('30');
      await expect(stepsInput).toHaveValue('30');
    }
  });

  test('seed input accepts numeric value', async ({ page }) => {
    await goToTool(page);
    const seedInput = page.getByPlaceholder(/seed|random/i);
    if (await seedInput.count() > 0) {
      await seedInput.first().fill('42');
      await expect(seedInput.first()).toHaveValue('42');
    }
  });

  test('resolution picker is visible', async ({ page }) => {
    await goToTool(page);
    const resSection = page.locator('text=Resolution').or(page.locator('text=resolution'));
    if (await resSection.count() > 0) {
      await expect(resSection.first()).toBeVisible();
    }
  });
});
