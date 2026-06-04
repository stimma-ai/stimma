import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { describeWithTestProvider, TEST_ALT_TOOL_PATH } from '../../helpers/fixtures';
import {
  openToolHopMenu,
  selectHopTool,
  getPromptValue,
  waitForToolViewReady,
} from '../../helpers/cross-tool';

describeWithTestProvider('Tool Hop', () => {
  test('hop between t2i tools carries over prompt', async ({ page }) => {
    await goToTool(page);

    // Fill prompt
    const prompt = 'a futuristic city skyline at dusk';
    await page.locator('.prompt-textarea').fill(prompt);

    // Open hop menu and select alt tool
    await openToolHopMenu(page, 'Test Text-to-Image');
    await selectHopTool(page, 'Test Alt Text-to-Image');

    // Should navigate to alt tool with prompt carried over
    await waitForToolViewReady(page);
    const loadedPrompt = await getPromptValue(page);
    expect(loadedPrompt).toContain('a futuristic city skyline at dusk');
    expect(page.url()).toContain('test-model-alt');
  });

  test('hop preserves negative prompt', async ({ page }) => {
    await goToTool(page);

    // Fill both prompts
    const prompt = 'a serene zen garden';
    await page.locator('.prompt-textarea').fill(prompt);

    // Find and fill negative prompt if the field exists
    const negPrompt = page.locator('textarea[placeholder*="negative"], .negative-prompt-textarea');
    if (await negPrompt.isVisible({ timeout: 2000 }).catch(() => false)) {
      await negPrompt.fill('blurry, low quality');
    }

    // Open hop menu from alt tool direction
    await openToolHopMenu(page, 'Test Text-to-Image');
    await selectHopTool(page, 'Test Alt Text-to-Image');

    await waitForToolViewReady(page);
    const loadedPrompt = await getPromptValue(page);
    expect(loadedPrompt).toContain('a serene zen garden');
  });

  test('hop from alt tool back to original tool', async ({ page }) => {
    // Start on the alt tool
    await goToTool(page, TEST_ALT_TOOL_PATH);

    const prompt = 'abstract geometric patterns';
    await page.locator('.prompt-textarea').fill(prompt);

    await openToolHopMenu(page, 'Test Alt Text-to-Image');
    await selectHopTool(page, 'Test Text-to-Image');

    await waitForToolViewReady(page);
    const loadedPrompt = await getPromptValue(page);
    expect(loadedPrompt).toContain('abstract geometric patterns');
    expect(page.url()).toContain('test-model');
    // Make sure it's the original, not the alt
    expect(page.url()).not.toContain('test-model-alt');
  });
});
