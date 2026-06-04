import { test, expect } from '@playwright/test';

test.describe('Chat', () => {
  test('chats landing page loads', async ({ page }) => {
    await page.goto('/chats');
    await expect(page.getByRole('heading', { name: 'Chats' })).toBeVisible({ timeout: 15000 });
  });

  test('can create new chat and see input', async ({ page }) => {
    await page.goto('/chats');
    await page.waitForLoadState('networkidle');
    // Use exact match to avoid matching the sidebar "Create new chat" icon button
    const newChatBtn = page.getByRole('button', { name: 'New Chat', exact: true });
    await expect(newChatBtn).toBeVisible({ timeout: 15000 });
    await newChatBtn.click();
    // Chat input should appear
    await expect(page.locator('.chat-input-textarea')).toBeVisible({ timeout: 10000 });
  });
});
