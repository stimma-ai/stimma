import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { describeWithTestProvider } from '../../helpers/fixtures';

describeWithTestProvider('LoRA Management', () => {
  test('LoRA section is visible if tool supports it', async ({ page }) => {
    await goToTool(page);
    const loraSection = page.getByText(/LoRA|Lora/i);
    if (await loraSection.count() > 0) {
      await expect(loraSection.first()).toBeVisible();
    }
  });
});
