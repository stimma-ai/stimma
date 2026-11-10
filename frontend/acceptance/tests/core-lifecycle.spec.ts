import { expect, test } from '../helpers/testbed';
import {
  addMediaToCollection,
  addMediaToProject,
  batchDeleteChats,
  batchRestoreChats,
  bulkMoveCollectionItems,
  bulkRemoveCollectionItems,
  createCollection,
  createCollectionSection,
  createChat,
  createProject,
  deleteCollection,
  deleteCollectionSection,
  deleteChat,
  deleteProject,
  generateMedia,
  getCollection,
  getChat,
  getProject,
  listCollections,
  listChats,
  listMedia,
  listProjects,
  moveCollectionItem,
  removeMediaFromProject,
  reorderCollectionSections,
  restoreCollection,
  restoreChat,
  updateCollection,
  updateCollectionSection,
  updateChat,
  updateProject,
  waitFor,
  waitForShell,
} from '../helpers/app';

test.describe('core object lifecycle acceptance', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('projects can be created, renamed, configured, and listed', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Lifecycle Project');

    const updated = await updateProject(page, project.id, {
      name: 'Acceptance Lifecycle Project Renamed',
      additional_instructions: 'Keep acceptance state project-scoped.',
      memory: 'Acceptance memory',
      chat_model_slug: 'acceptance-model',
    });

    expect(updated.name).toBe('Acceptance Lifecycle Project Renamed');
    expect(updated.asset_count).toBe(0);

    const loaded = await getProject(page, project.id);
    expect(loaded.name).toBe('Acceptance Lifecycle Project Renamed');
    expect(loaded.chat_model_slug).toBe('acceptance-model');

    const projects = await listProjects(page);
    expect(projects.some((item) => item.id === project.id)).toBe(true);
  });

  test('media can be attached to and removed from a project', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Attach Project');
    const prompt = `acceptance project attach ${Date.now()}`;
    const media = await generateMedia(page, prompt);

    await addMediaToProject(page, project.id, [media.id]);

    await waitFor(async () => {
      const projectMedia = await listMedia(page, {
        page: 1,
        page_size: 20,
        project_id: project.id,
        prompt_query: prompt,
      });
      return projectMedia.some((item) => item.id === media.id) ? projectMedia : null;
    }, 30000);

    await removeMediaFromProject(page, project.id, media.id);

    await waitFor(async () => {
      const projectMedia = await listMedia(page, {
        page: 1,
        page_size: 20,
        project_id: project.id,
        prompt_query: prompt,
      });
      return projectMedia.some((item) => item.id === media.id) ? null : projectMedia;
    }, 30000);
  });

  test('deleting a project removes project scope but leaves assets in the library', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Delete Project');
    const prompt = `acceptance project delete ${Date.now()}`;
    const media = await generateMedia(page, prompt, project.id);

    await deleteProject(page, project.id);

    const projects = await listProjects(page);
    expect(projects.some((item) => item.id === project.id)).toBe(false);

    const globalMedia = await listMedia(page, { page: 1, page_size: 20, prompt_query: prompt });
    expect(globalMedia.some((item) => item.id === media.id)).toBe(true);
  });

  test('collections can be renamed, moved into project scope, and listed there', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Collection Project');
    const collection = await createCollection(page, 'Acceptance Movable Collection');

    const updated = await updateCollection(page, collection.id, {
      name: 'Acceptance Project Collection Renamed',
      project_id: project.id,
    });
    expect(updated.name).toBe('Acceptance Project Collection Renamed');
    expect(updated.project_id).toBe(project.id);

    const projectCollections = await listCollections(page, project.id);
    expect(projectCollections.some((item) => item.id === collection.id)).toBe(true);

    const globalCollections = await listCollections(page);
    expect(globalCollections.some((item) => item.id === collection.id)).toBe(false);
  });

  test('collections can be soft-deleted and restored', async ({ page }) => {
    const collection = await createCollection(page, 'Acceptance Restorable Collection');

    await deleteCollection(page, collection.id);
    const afterDelete = await listCollections(page);
    expect(afterDelete.some((item) => item.id === collection.id)).toBe(false);

    const restored = await restoreCollection(page, collection.id);
    expect(restored.id).toBe(collection.id);

    const afterRestore = await listCollections(page);
    expect(afterRestore.some((item) => item.id === collection.id)).toBe(true);
  });

  test('collection sections can be created, renamed, collapsed, reordered, and deleted', async ({ page }) => {
    const collection = await createCollection(page, 'Acceptance Section Collection');
    const alpha = await createCollectionSection(page, collection.id, 'Alpha');
    const beta = await createCollectionSection(page, collection.id, 'Beta');

    const renamed = await updateCollectionSection(page, alpha.id, {
      name: 'Alpha Renamed',
      is_collapsed: true,
    });
    expect(renamed.name).toBe('Alpha Renamed');
    expect(renamed.is_collapsed).toBe(true);

    await reorderCollectionSections(page, collection.id, [beta.id, alpha.id]);
    const reordered = await getCollection(page, collection.id);
    const betaIndex = reordered.sections.findIndex((section) => section.id === beta.id);
    const alphaIndex = reordered.sections.findIndex((section) => section.id === alpha.id);
    expect(betaIndex).toBeGreaterThanOrEqual(0);
    expect(alphaIndex).toBeGreaterThanOrEqual(0);
    expect(betaIndex).toBeLessThan(alphaIndex);

    await deleteCollectionSection(page, beta.id);
    const afterDelete = await getCollection(page, collection.id);
    expect(afterDelete.sections.some((section) => section.id === beta.id)).toBe(false);
  });

  test('collection items can be moved between sections', async ({ page }) => {
    const prompt = `acceptance collection move ${Date.now()}`;
    const media = await generateMedia(page, prompt);
    const collection = await createCollection(page, 'Acceptance Move Collection');
    const target = await createCollectionSection(page, collection.id, 'Target');

    await addMediaToCollection(page, collection.id, [media.id]);
    const withMedia = await getCollection(page, collection.id);
    const source = withMedia.sections.find((section) => section.items.some((item) => item.id === media.id));
    expect(source).toBeTruthy();

    await moveCollectionItem(page, collection.id, media.id, source!.id, target.id, 0);

    await waitFor(async () => {
      const loaded = await getCollection(page, collection.id);
      const moved = loaded.sections.find((section) => section.id === target.id);
      return moved?.items.some((item) => item.id === media.id) ? loaded : null;
    }, 30000);
  });

  test('collection items can be bulk-moved and bulk-removed', async ({ page }) => {
    const stamp = Date.now();
    const first = await generateMedia(page, `acceptance collection bulk first ${stamp}`);
    const second = await generateMedia(page, `acceptance collection bulk second ${stamp}`);
    const collection = await createCollection(page, 'Acceptance Bulk Collection');
    const target = await createCollectionSection(page, collection.id, 'Bulk Target');

    await addMediaToCollection(page, collection.id, [first.id, second.id]);
    await bulkMoveCollectionItems(page, collection.id, [first.id, second.id], target.id);

    await waitFor(async () => {
      const loaded = await getCollection(page, collection.id);
      const targetSection = loaded.sections.find((section) => section.id === target.id);
      const ids = new Set(targetSection?.items.map((item) => item.id) ?? []);
      return ids.has(first.id) && ids.has(second.id) ? loaded : null;
    }, 30000);

    await bulkRemoveCollectionItems(page, collection.id, [first.id, second.id]);
    const afterRemove = await getCollection(page, collection.id);
    const remainingIds = new Set(afterRemove.sections.flatMap((section) => section.items.map((item) => item.id)));
    expect(remainingIds.has(first.id)).toBe(false);
    expect(remainingIds.has(second.id)).toBe(false);
  });

  test('chats can be created, renamed, and listed', async ({ page }) => {
    const chat = await createChat(page, 'Acceptance Lifecycle Chat');

    const updated = await updateChat(page, chat.id, { name: 'Acceptance Lifecycle Chat Renamed' });
    expect(updated.name).toBe('Acceptance Lifecycle Chat Renamed');

    const loaded = await getChat(page, chat.id);
    expect(loaded.name).toBe('Acceptance Lifecycle Chat Renamed');

    const chats = await listChats(page);
    expect(chats.items.some((item) => item.id === chat.id)).toBe(true);
  });

  test('project-scoped chats list only under their project', async ({ page }) => {
    const project = await createProject(page, 'Acceptance Chat Project');
    const projectChat = await createChat(page, 'Acceptance Project Chat', project.id);
    const globalChat = await createChat(page, 'Acceptance Global Chat');

    const projectChats = await listChats(page, { projectId: project.id });
    expect(projectChats.items.some((item) => item.id === projectChat.id)).toBe(true);
    expect(projectChats.items.some((item) => item.id === globalChat.id)).toBe(false);
  });

  test('chats can be soft-deleted and restored', async ({ page }) => {
    const chat = await createChat(page, 'Acceptance Restorable Chat');

    await deleteChat(page, chat.id);
    const activeChats = await listChats(page);
    expect(activeChats.items.some((item) => item.id === chat.id)).toBe(false);

    const deletedChats = await listChats(page, { includeDeleted: true });
    expect(deletedChats.items.some((item) => item.id === chat.id && item.deleted_at)).toBe(true);

    const restored = await restoreChat(page, chat.id);
    expect(restored.deleted_at).toBeFalsy();

    const afterRestore = await listChats(page);
    expect(afterRestore.items.some((item) => item.id === chat.id)).toBe(true);
  });

  test('chats can be batch-deleted and batch-restored', async ({ page }) => {
    const first = await createChat(page, 'Acceptance Batch Chat A');
    const second = await createChat(page, 'Acceptance Batch Chat B');

    await batchDeleteChats(page, [first.id, second.id]);
    const afterDelete = await listChats(page);
    expect(afterDelete.items.some((item) => item.id === first.id || item.id === second.id)).toBe(false);

    await batchRestoreChats(page, [first.id, second.id]);
    const afterRestore = await listChats(page);
    const restoredIds = new Set(afterRestore.items.map((item) => item.id));
    expect(restoredIds.has(first.id)).toBe(true);
    expect(restoredIds.has(second.id)).toBe(true);
  });

  test('chat shortcuts are disarmed when the KeepAlive view is deactivated', async ({ page }) => {
    const first = await createChat(page, 'Acceptance KeepAlive Chat A');
    const second = await createChat(page, 'Acceptance KeepAlive Chat B');
    const chatDeleteRequests: string[] = [];

    // Abort the destructive request if the regression returns so a failing
    // acceptance run cannot wipe the sandbox's other lifecycle fixtures.
    await page.route('**/api/chats/batch/delete', async (route) => {
      const request = route.request();
      chatDeleteRequests.push(`${request.method()} ${new URL(request.url()).pathname}`);
      await route.abort();
    });

    const readinessDismiss = page.getByTestId('readiness-dismiss');
    if (await readinessDismiss.isVisible({ timeout: 5000 }).catch(() => false)) {
      await readinessDismiss.click();
      await expect(page.getByTestId('readiness-panel')).toBeHidden();
    }

    await page.getByRole('button', { name: 'Chats', exact: true }).first().click();
    await expect(page).toHaveURL(/\/chats$/);
    await expect(page.getByText(first.name, { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByText(second.name, { exact: true })).toBeVisible({ timeout: 30000 });

    // Arm a selection through the normal row interactions, then navigate
    // through the app shell so KeepAlive deactivates Chats instead of
    // unmounting it.
    await page.getByTestId(`chat-row-${first.id}`).getByRole('button').click();
    await page.getByTestId(`chat-row-${second.id}`).getByRole('button').click();
    await expect(page.getByTitle('Delete selected')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTitle('Delete selected')).toBeHidden();

    // Re-arm the selection that deactivation must clear.
    await page.getByTestId(`chat-row-${first.id}`).getByRole('button').click();
    await page.getByTestId(`chat-row-${second.id}`).getByRole('button').click();
    await expect(page.getByTitle('Delete selected')).toBeVisible();
    await page.getByRole('button', { name: 'Tools', exact: true }).first().click();
    await expect(page).toHaveURL(/\/tools$/);

    // The inactive Chats view must neither retain the old selection nor
    // respond to common shortcuts pressed on another screen.
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press('Control+A');
    await page.keyboard.press('Backspace');
    await expect.poll(() => chatDeleteRequests).toEqual([]);

    await page.getByRole('button', { name: 'Chats', exact: true }).first().click();
    await expect(page).toHaveURL(/\/chats$/);
    await expect(page.getByTitle('Delete selected')).toBeHidden();

    // Arm another selection so this specifically proves that Backspace in a
    // rich-text editor cannot fall through to the batch-delete shortcut.
    await page.getByTestId(`chat-row-${first.id}`).getByRole('button').click();
    await page.getByTestId(`chat-row-${second.id}`).getByRole('button').click();
    await expect(page.getByTitle('Delete selected')).toBeVisible();

    // Rich-text editors in the active document own Cmd+A and Backspace.
    await page.evaluate(() => {
      const editor = document.createElement('div');
      editor.contentEditable = 'true';
      editor.dataset.testid = 'acceptance-contenteditable';
      editor.textContent = 'editable text';
      document.body.appendChild(editor);
      editor.focus();
    });
    await page.keyboard.press('Backspace');
    await expect.poll(() => chatDeleteRequests).toEqual([]);
    await expect(page.getByTitle('Delete selected')).toBeVisible();
    await page.getByTestId('acceptance-contenteditable').evaluate((editor) => editor.remove());

    // Once selection is cleared, a bare Backspace remains harmless.
    await page.keyboard.press('Escape');
    await expect(page.getByTitle('Delete selected')).toBeHidden();
    await page.keyboard.press('Backspace');
    await expect.poll(() => chatDeleteRequests).toEqual([]);

    const activeChats = await listChats(page);
    const activeIds = new Set(activeChats.items.map((item) => item.id));
    expect(activeIds.has(first.id)).toBe(true);
    expect(activeIds.has(second.id)).toBe(true);
  });
});
