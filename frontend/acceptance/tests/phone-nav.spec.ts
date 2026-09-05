import { expect, test } from '@playwright/test';
import { createChat } from '../helpers/app';
import { settleAnyViewport } from '../helpers/viewport';

/**
 * Phone lane, navigation model: every hub owns a stack; back pops the stack
 * and, at the root, returns to the previous hub; tapping a tab restores that
 * hub's top; tapping the active tab pops to root.
 */
test.describe('phone lane: two-layer navigation', () => {
  test('hub stacks and hub history', async ({ page }) => {
    await page.goto('/chats');
    await settleAnyViewport(page);
    const chat = await createChat(page, 'Nav stack chat');
    await page.goto('/chats');
    await settleAnyViewport(page);
    const tab = (name: string) => page.locator('.compact-tab-bar').getByRole('button', { name, exact: true });
    const back = page.getByRole('button', { name: 'Back' });

    // Chats → chat (push inside the Chats stack).
    await page.locator('.cursor-pointer.group').filter({ hasText: 'Nav stack chat' }).first().click({ position: { x: 300, y: 24 } });
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));

    // Switch hub: Boards. Then back to Chats: the chat is still there.
    await tab('Boards').click();
    await expect(page).toHaveURL(/\/boards$/);
    await tab('Chats').click();
    await expect(page).toHaveURL(new RegExp(`/chat/${chat.id}$`));

    // Back pops the Chats stack to its root.
    await back.click();
    await expect(page).toHaveURL(/\/chats$/);

    // At a hub root there is no back control (the hub's avatar sits there);
    // the OS back gesture and the tab bar are the way out, as on native.
    await expect(back).toHaveCount(0);

    // Workspace: open a tool, back returns to Workspace, not Library.
    await tab('Workspace').click();
    await page.goto(`/tools/test:text-to-image:test-model`);
    await settleAnyViewport(page);
    await expect(page.locator('.compact-header h1')).toContainText('Test Text-to-Image');
    await back.click();
    await expect(page).toHaveURL(/\/(workspace|tools)$/);

    // Tapping the active tab pops to root.
    await page.goto(`/tools/test:text-to-image:test-model`);
    await settleAnyViewport(page);
    await tab('Workspace').click();
    await expect(page).toHaveURL(/\/(workspace|tools)$/);
  });
});
