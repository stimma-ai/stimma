import { expect, test } from '@playwright/test';
import {
  createChat,
  createProject,
  listChatItems,
  listChats,
  sendChatMessage,
  waitForChatItem,
  waitForShell,
} from '../helpers/app';

test.describe('chat agent acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('chat can send a message and receive a deterministic dummy LLM reply', async ({ page }) => {
    const chat = await createChat(page, 'Acceptance Agent Chat');
    const message = `acceptance chat hello ${Date.now()}`;

    await page.goto(`/chat/${chat.id}`);
    await sendChatMessage(page, message);

    await expect(page.getByText(message, { exact: true })).toBeVisible({ timeout: 30000 });
    const assistant = await waitForChatItem(
      page,
      chat.id,
      (item) => item.item_type === 'assistant_message' &&
        Boolean(item.message_text?.includes(`Acceptance dummy reply: ${message}`)),
    );
    expect(assistant.message_text).toContain(message);
    await expect(page.getByText(`Acceptance dummy reply: ${message}`)).toBeVisible({ timeout: 30000 });

    await page.reload();
    await expect(page.getByText(message, { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByText(`Acceptance dummy reply: ${message}`)).toBeVisible({ timeout: 30000 });
  });

  test('project-scoped chat sends through the dummy LLM and stays scoped', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Agent Project');
    const chat = await createChat(page, 'Acceptance Project Agent Chat', project.id);
    const message = `acceptance project chat ${Date.now()}`;

    await page.goto(`/chat/${chat.id}`);
    await sendChatMessage(page, message);

    await waitForChatItem(
      page,
      chat.id,
      (item) => item.item_type === 'assistant_message' &&
        Boolean(item.message_text?.includes(`Acceptance dummy reply: ${message}`)),
    );

    const projectChats = await listChats(page, { projectId: project.id });
    expect(projectChats.items.some((item) => item.id === chat.id)).toBe(true);

    await page.goto(`/projects/${project.id}/chats`);
    await expect(page.getByText('Acceptance Project Agent Chat').first()).toBeVisible({ timeout: 30000 });
  });

  test('chat item history persists user and assistant messages through the API', async ({ page }) => {
    const chat = await createChat(page, 'Acceptance Agent Persistence Chat');
    const message = `acceptance persistence ${Date.now()}`;

    await page.goto(`/chat/${chat.id}`);
    await sendChatMessage(page, message);
    await waitForChatItem(
      page,
      chat.id,
      (item) => item.item_type === 'assistant_message' &&
        Boolean(item.message_text?.includes(`Acceptance dummy reply: ${message}`)),
    );

    const items = await listChatItems(page, chat.id);
    expect(items.some((item) => item.item_type === 'user_message' && item.message_text === message)).toBe(true);
    expect(items.some((item) => item.item_type === 'assistant_message' &&
      item.message_text?.includes(`Acceptance dummy reply: ${message}`))).toBe(true);
  });
});
