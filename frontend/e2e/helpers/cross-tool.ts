import { type Page, expect } from '@playwright/test';

/**
 * Click a completed result tile in the queue panel to open the slideshow.
 * The slideshow overlay renders GenerateMoreMenu and SendToToolMenu in its info panel.
 */
export async function openSlideshowFromQueue(page: Page) {
  const queuePanel = page.locator('.bg-surface-overlay').filter({ hasText: 'Queue' });
  const img = queuePanel.locator('img').first();
  await expect(img).toBeVisible({ timeout: 10000 });
  await img.click();
  // Wait for slideshow overlay to appear (SlideshowInfoPanel has "Actions" heading)
  await expect(page.getByText('Actions', { exact: true })).toBeVisible({ timeout: 5000 });
}

/**
 * Click the "Generate more like this" button in the slideshow info panel,
 * wait for the dropdown menu to load tools.
 */
export async function openGenerateMoreMenu(page: Page) {
  const btn = page.getByRole('button', { name: 'Generate more like this' });
  await expect(btn).toBeVisible({ timeout: 5000 });
  await btn.click();
  // Wait for the teleported dropdown menu to appear and finish loading
  // The menu shows "Loading tools..." then tool buttons
  await expect(page.getByText('Loading tools...')).toBeHidden({ timeout: 10000 });
}

/**
 * Select a tool by name from the generate-more dropdown menu.
 */
export async function selectGenerateMoreTool(page: Page, toolName: string) {
  // The teleported menu contains buttons with tool names
  const menuItem = page.locator('.fixed.bg-surface').getByRole('button', { name: toolName });
  await expect(menuItem).toBeVisible({ timeout: 5000 });
  await menuItem.click();
}

/**
 * Click the "Send to Tool" button in the slideshow info panel,
 * wait for the dropdown to load tools.
 */
export async function openSendToMenu(page: Page) {
  const btn = page.getByRole('button', { name: 'Send to Tool' });
  await expect(btn).toBeVisible({ timeout: 5000 });
  await btn.click();
  // Wait for tools to load
  await expect(page.getByText('Loading tools...')).toBeHidden({ timeout: 10000 });
}

/**
 * Select a tool by name from the send-to dropdown menu.
 */
export async function selectSendToTool(page: Page, toolName: string) {
  const menuItem = page.locator('.fixed.bg-surface').getByRole('button', { name: toolName });
  await expect(menuItem).toBeVisible({ timeout: 5000 });
  await menuItem.click();
}

/**
 * Click the tool name heading (HopToToolMenu) to open the hop dropdown.
 * The heading is an h2 inside a button with a chevron.
 */
export async function openToolHopMenu(page: Page, currentToolName: string) {
  // HopToToolMenu renders: <button><h2>ToolName</h2><svg chevron/></button>
  const hopButton = page.locator('button').filter({ has: page.locator(`h2:text("${currentToolName}")`) });
  await expect(hopButton).toBeVisible({ timeout: 5000 });
  await hopButton.click();
  // Wait for tools to load
  await expect(page.getByText('Loading tools...')).toBeHidden({ timeout: 10000 });
}

/**
 * Select a tool from the hop dropdown menu.
 */
export async function selectHopTool(page: Page, toolName: string) {
  const menuItem = page.locator('.fixed.bg-surface').getByRole('button', { name: toolName });
  await expect(menuItem).toBeVisible({ timeout: 5000 });
  await menuItem.click();
}

/**
 * Read the current value of the prompt textarea.
 */
export async function getPromptValue(page: Page): Promise<string> {
  const textarea = page.locator('.prompt-textarea');
  await expect(textarea).toBeVisible({ timeout: 5000 });
  return textarea.inputValue();
}

/**
 * Wait for the tool view to finish loading after navigation.
 * After a hop, generate-more, or send-to, the tool view navigates and loads.
 */
export async function waitForToolViewReady(page: Page, timeout = 15000) {
  await page.locator('.prompt-textarea').waitFor({ state: 'visible', timeout });
}

/**
 * Close the slideshow overlay by pressing Escape.
 */
export async function closeSlideshow(page: Page) {
  await page.keyboard.press('Escape');
  // Wait for slideshow to close
  await expect(page.getByText('Actions', { exact: true })).toBeHidden({ timeout: 3000 });
}
