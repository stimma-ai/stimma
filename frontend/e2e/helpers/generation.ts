import { type Page, expect } from '@playwright/test';

/** Fill the prompt textarea and click the Run button to submit a generation job. */
export async function submitGeneration(page: Page, prompt: string) {
  const textarea = page.locator('.prompt-textarea');
  await textarea.fill(prompt);
  const runButton = page.getByRole('button', { name: /^Run/ });
  await expect(runButton).toBeEnabled({ timeout: 5000 });
  await runButton.click();
}

/**
 * Wait for at least one generation job to complete.
 * Completed jobs show an img or video in the Queue panel on the right.
 */
export async function waitForJobComplete(page: Page, timeout = 30000) {
  // Queue panel contains an h3 "Queue" and completed jobs render <img> elements
  // Use the panel's bg class as a stable selector
  const queuePanel = page.locator('.bg-surface-overlay').filter({ hasText: 'Queue' });
  await queuePanel.locator('img').first().waitFor({ state: 'visible', timeout });
}

/** Get all completed result tiles in the queue panel. */
export async function getResultTiles(page: Page) {
  const queuePanel = page.locator('.bg-surface-overlay').filter({ hasText: 'Queue' });
  return queuePanel.locator('img');
}

/** Get the Run button element. */
export function getRunButton(page: Page) {
  return page.getByRole('button', { name: /^Run/ });
}
