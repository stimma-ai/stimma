import { type Page, expect } from '@playwright/test';
import { TEST_TOOL_PATH } from './fixtures';

/**
 * Wait for the sidebar navigation to appear (indicates backend data loaded).
 */
export async function waitForApp(page: Page, timeout = 30000) {
  await expect(page.getByText('All Assets')).toBeVisible({ timeout });
}

/** Navigate to the browse view and wait for the page to be ready. */
export async function goToBrowse(page: Page) {
  await page.goto('/browse');
  await waitForApp(page);
}

/** Navigate to a tool by its full tool ID and wait for the form to load. */
export async function goToTool(page: Page, toolPath = TEST_TOOL_PATH) {
  await page.goto(toolPath);
  // Wait for the prompt textarea to be visible (means tool loaded)
  await page.locator('.prompt-textarea').waitFor({ state: 'visible', timeout: 30000 });
}

/** Navigate to the tools listing page. */
export async function goToTools(page: Page) {
  await page.goto('/tools');
  await waitForApp(page);
}

/** Navigate to a chat by ID. */
export async function goToChat(page: Page, chatId: string) {
  await page.goto(`/chat/${chatId}`);
  await page.locator('.chat-input-textarea').waitFor({ state: 'visible', timeout: 15000 });
}
