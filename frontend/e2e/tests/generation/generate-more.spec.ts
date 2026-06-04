import { test, expect } from '@playwright/test';
import { goToTool } from '../../helpers/navigation';
import { submitGeneration, waitForJobComplete } from '../../helpers/generation';
import { describeWithTestProvider } from '../../helpers/fixtures';
import {
  openSlideshowFromQueue,
  openGenerateMoreMenu,
  selectGenerateMoreTool,
  getPromptValue,
  waitForToolViewReady,
} from '../../helpers/cross-tool';

describeWithTestProvider('Generate More Like This', () => {
  test('generate-more menu shows original and alt tools', async ({ page }) => {
    await goToTool(page);
    await submitGeneration(page, 'a red bird on a branch');
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openGenerateMoreMenu(page);

    // Should show the original tool and the alt tool
    await expect(page.getByRole('button', { name: 'Test Text-to-Image' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Test Alt Text-to-Image' })).toBeVisible();
  });

  test('generate more with same tool carries over prompt', async ({ page }) => {
    const prompt = 'a golden retriever playing fetch';
    await goToTool(page);
    await submitGeneration(page, prompt);
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openGenerateMoreMenu(page);
    await selectGenerateMoreTool(page, 'Test Text-to-Image');

    // Should navigate to the tool with prompt loaded
    await waitForToolViewReady(page);
    const loadedPrompt = await getPromptValue(page);
    expect(loadedPrompt).toContain('a golden retriever playing fetch');
  });

  test('generate more with different t2i tool carries over prompt', async ({ page }) => {
    const prompt = 'a majestic castle on a hill';
    await goToTool(page);
    await submitGeneration(page, prompt);
    await waitForJobComplete(page);

    await openSlideshowFromQueue(page);
    await openGenerateMoreMenu(page);
    await selectGenerateMoreTool(page, 'Test Alt Text-to-Image');

    // Should navigate to the alt tool with prompt carried over
    await waitForToolViewReady(page);
    const loadedPrompt = await getPromptValue(page);
    expect(loadedPrompt).toContain('a majestic castle on a hill');
    // Verify we're on the alt tool by checking the URL
    expect(page.url()).toContain('test-model-alt');
  });
});
