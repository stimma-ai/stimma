import { expect, type Page } from '@playwright/test';

export const TEST_T2I_TOOL_ID = 'test:text-to-image:test-model';
export const TEST_T2I_TOOL_URL = `/tools/${TEST_T2I_TOOL_ID}`;
export const TEST_I2I_TOOL_ID = 'test:image-to-image:test-edit';
export const TEST_I2I_TOOL_URL = `/tools/${TEST_I2I_TOOL_ID}`;
export const TEST_UPSCALE_TOOL_ID = 'test:upscale-image:test-upscale';
export const TEST_UPSCALE_TOOL_URL = `/tools/${TEST_UPSCALE_TOOL_ID}`;

type MediaItem = {
  id: number;
  file_hash?: string;
  file_path?: string;
  width?: number;
  height?: number;
  generation_metadata?: string | null;
  markers?: { id: number; name: string }[];
};

type Marker = {
  id: number;
  name: string;
};

type Project = {
  id: number;
  name: string;
  asset_count?: number;
  chat_count?: number;
  board_count?: number;
};

type Board = {
  id: number;
  name: string;
  project_id?: number | null;
  sections: BoardSection[];
  asset_count?: number;
};

type BoardSection = {
  id: number;
  name?: string | null;
  is_default: boolean;
  is_collapsed: boolean;
  display_order: number;
  items: MediaItem[];
  item_count: number;
};

type Chat = {
  id: number;
  name: string;
  project_id?: number | null;
  deleted_at?: string | null;
};

type ChatItem = {
  id: number;
  chat_id: number;
  item_type: string;
  message_text?: string | null;
  item_metadata?: Record<string, unknown> | null;
};

export async function waitForShell(page: Page) {
  await continueWithoutAccountIfNeeded(page);
  await expect(page.getByText('All Assets', { exact: true }).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Tools', { exact: true }).first()).toBeVisible();
}

export async function goToBrowse(page: Page) {
  await page.goto('/browse');
  await waitForShell(page);
  const homeHeading = page.getByRole('heading', { name: 'What would you like to create today?' });
  const uploadButton = page.getByTitle('Upload assets');
  if (await homeHeading.isVisible({ timeout: 1000 }).catch(() => false)) {
    await page.getByRole('link', { name: 'View all' }).first().click();
  }
  if (!(await uploadButton.isVisible({ timeout: 3000 }).catch(() => false))) {
    await page.getByRole('button', { name: 'All Assets' }).click();
  }
  await expect(page).toHaveURL(/\/browse/, { timeout: 10000 });
  await expect(homeHeading).toBeHidden({ timeout: 10000 });
  await expect(uploadButton).toBeVisible({ timeout: 10000 });
}

export async function openTool(page: Page, projectId?: number) {
  await openToolById(page, TEST_T2I_TOOL_ID, projectId);
}

export async function openToolById(page: Page, toolId: string, projectId?: number, extraQuery: Record<string, string> = {}) {
  const query = new URLSearchParams(extraQuery);
  if (projectId) query.set('project_id', String(projectId));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  const toolUrl = `/tools/${toolId}`;
  const url = `${toolUrl}${suffix}`;
  await page.goto(url);
  await continueWithoutAccountIfNeeded(page);
  if (!page.url().includes(toolUrl)) {
    await page.goto(url);
  }
  await expect(page.getByRole('button', { name: /^Run/ })).toBeVisible({ timeout: 30000 });
}

export async function openPromptToolById(page: Page, toolId: string, projectId?: number, extraQuery: Record<string, string> = {}) {
  await openToolById(page, toolId, projectId, extraQuery);
  await promptInput(page).waitFor({ state: 'visible', timeout: 30000 });
  await expect(page.getByRole('button', { name: /^Run/ })).toBeEnabled({ timeout: 10000 });
}

export async function submitGeneration(page: Page, prompt: string) {
  await promptInput(page).fill(prompt);
  const runButton = page.getByRole('button', { name: /^Run/ });
  await expect(runButton).toBeEnabled({ timeout: 10000 });
  await runButton.click({ force: true });
}

export async function setBatchSize(page: Page, size: number) {
  await page.getByRole('button', { name: 'Batch size' }).click();
  const input = page.getByRole('spinbutton').first();
  await input.fill(String(size));
  await input.press('Enter');
  await expect(page.getByRole('button', { name: new RegExp(`^Run.*×${size}`) })).toBeVisible({ timeout: 5000 });
}

export async function generateMedia(page: Page, prompt: string, projectId?: number): Promise<MediaItem> {
  await openTool(page, projectId);
  await submitGeneration(page, prompt);
  const media = await waitForGeneratedMedia(page, { prompt, projectId });
  return media[0];
}

export async function waitForQueueImage(page: Page) {
  await page.locator('.bg-surface-overlay').filter({ hasText: 'Queue' }).locator('img').first()
    .waitFor({ state: 'visible', timeout: 30000 });
}

export async function openMediaFromBrowse(page: Page, mediaId: number) {
  await goToBrowse(page);
  const gridItem = page.getByTestId(`media-grid-item-${mediaId}`);
  await expect(gridItem).toBeVisible({ timeout: 30000 });
  await gridItem.click();
  await expect(page.getByText('Actions', { exact: true })).toBeVisible({ timeout: 10000 });
}

export async function apiJSON<T>(page: Page, path: string, init: RequestInit = {}): Promise<T> {
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const response = await page.request.fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(profileId ? { 'X-Profile-ID': profileId } : {}),
      ...(init.headers || {}),
    },
  });
  if (!response.ok()) {
    throw new Error(`${init.method || 'GET'} ${path} failed with ${response.status()}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export async function createProject(page: Page, name: string): Promise<{ id: number; name: string }> {
  return apiJSON(page, '/api/projects', {
    method: 'POST',
    data: { name },
  } as any);
}

export async function listProjects(page: Page): Promise<Project[]> {
  return apiJSON(page, '/api/projects');
}

export async function getProject(page: Page, projectId: number): Promise<Project> {
  return apiJSON(page, `/api/projects/${projectId}`);
}

export async function updateProject(page: Page, projectId: number, data: Record<string, unknown>): Promise<Project> {
  return apiJSON(page, `/api/projects/${projectId}`, { method: 'PUT', data } as any);
}

export async function deleteProject(page: Page, projectId: number) {
  return apiJSON(page, `/api/projects/${projectId}`, { method: 'DELETE' });
}

export async function addMediaToProject(page: Page, projectId: number, mediaIds: number[]) {
  return apiJSON(page, `/api/projects/${projectId}/assets`, {
    method: 'POST',
    data: { media_ids: mediaIds },
  } as any);
}

export async function removeMediaFromProject(page: Page, projectId: number, mediaId: number) {
  return apiJSON(page, `/api/projects/${projectId}/assets/${mediaId}`, { method: 'DELETE' });
}

export async function waitForGeneratedMedia(
  page: Page,
  options: { prompt?: string; projectId?: number; expectedCount?: number; toolId?: string } = {},
): Promise<MediaItem[]> {
  const query = new URLSearchParams({
    page: '1',
    page_size: '20',
    tool_id: options.toolId ?? TEST_T2I_TOOL_ID,
    sort_by: 'created_desc',
  });
  if (options.prompt) query.set('prompt_query', options.prompt);
  if (options.projectId != null) query.set('project_id', String(options.projectId));

  const expectedCount = options.expectedCount ?? 1;
  let lastCount = 0;
  try {
    return await waitFor(async () => {
      const media = await apiJSON<{ items: MediaItem[] }>(page, `/api/media?${query.toString()}`);
      lastCount = media.items.length;
      return media.items.length >= expectedCount ? media.items : null;
    }, 30000, `generated media count >= ${expectedCount}`);
  } catch (err) {
    const detail = [
      `Timed out waiting for generated media count >= ${expectedCount}`,
      `last_count=${lastCount}`,
      `query=${query.toString()}`,
    ].join('; ');
    throw new Error(`${detail}; cause=${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function listMedia(page: Page, params: Record<string, string | number | boolean>): Promise<MediaItem[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value));
  }
  const media = await apiJSON<{ items: MediaItem[] }>(page, `/api/media?${query.toString()}`);
  return media.items;
}

export async function getMedia(page: Page, mediaId: number, includeTrashed = false): Promise<MediaItem> {
  const suffix = includeTrashed ? '?include_trashed=true' : '';
  return apiJSON(page, `/api/media/${mediaId}${suffix}`);
}

export async function seedPendingToolInput(
  page: Page,
  toolId: string,
  mediaIds: number[],
  options: { projectId?: number; mode?: 'single' | 'batch'; field?: 'input_images' | 'input_videos' } = {},
) {
  await loadProfilesIntoPage(page);
  const entries: MediaItem[] = [];
  for (const mediaId of mediaIds) {
    const media = await getMedia(page, mediaId);
    const copied = await apiJSON<{ path: string; filename?: string }>(
      page,
      `/api/generate/copy-to-reference?source_path=${encodeURIComponent(media.file_path || '')}`,
      { method: 'POST' },
    );
    entries.push({
      id: media.id,
      file_hash: media.file_hash,
      file_path: copied.path,
      width: media.width,
      height: media.height,
    });
  }

  await page.evaluate(({ toolId, projectId, entries, mode, field }) => {
    const bundleId = localStorage.getItem('stimma_bundle_id') || '';
    const sandbox = localStorage.getItem('stimma_sandbox') || 'default';
    const prefix = bundleId ? `stimma_${bundleId}_${sandbox}` : 'stimma';
    const profileId = localStorage.getItem('profileId');
    const profiles = (window as any).__stimmaAcceptanceProfiles || [];
    const dbGuid = profiles.find((profile: any) => profile.id === profileId)?.db_guid || profileId;
    const scopedToolId = projectId ? `${toolId}__project_${projectId}` : toolId;
    const safeToolId = scopedToolId.replace(/:/g, '_');
    const key = `${prefix}_${dbGuid}_tool_${safeToolId}_pending_input`;
    const items = entries.map((entry: any) => ({
      mediaId: entry.id,
      hash: entry.file_hash,
      path: entry.file_path,
      filename: entry.file_path?.split('/').pop() || entry.file_hash,
      width: entry.width,
      height: entry.height,
    }));
    const value = mode === 'batch'
      ? { mode: 'batch', field: field || 'input_images', items }
      : { inputImages: items, appendImages: true };
    sessionStorage.setItem(key, JSON.stringify(value));
  }, {
    toolId,
    projectId: options.projectId ?? null,
    entries,
    mode: options.mode ?? 'single',
    field: options.field ?? 'input_images',
  });
}

export async function loadProfilesIntoPage(page: Page) {
  const response = await apiJSON<any[] | { profiles?: any[]; items?: any[] }>(page, '/api/profiles');
  const profiles = Array.isArray(response) ? response : (response.profiles || response.items || []);
  await page.evaluate((profiles) => {
    (window as any).__stimmaAcceptanceProfiles = profiles;
  }, profiles);
}

export async function openToolWithPendingInput(page: Page, toolId: string, projectId?: number) {
  await loadProfilesIntoPage(page);
  await openToolById(page, toolId, projectId, { loadInput: String(Date.now()) });
  await expect(page.locator('[data-drop-zone="media-picker-image"] img').first()).toBeVisible({ timeout: 30000 });
}

export function mediaSourceIds(media: MediaItem): number[] {
  if (!media.generation_metadata) return [];
  try {
    const parsed = JSON.parse(media.generation_metadata);
    return (parsed.source_inputs || [])
      .map((source: any) => Number(source.media_id))
      .filter((id: number) => Number.isFinite(id));
  } catch {
    return [];
  }
}

export async function waitForGeneratedFromSource(
  page: Page,
  toolId: string,
  sourceMediaIds: number[],
  expectedCount = 1,
): Promise<MediaItem[]> {
  return waitFor(async () => {
    const candidates = await listMedia(page, {
      page: 1,
      page_size: 50,
      tool_ids: toolId,
      sort_by: 'created_desc',
    });
    const matches: MediaItem[] = [];
    for (const candidate of candidates) {
      const media = await getMedia(page, candidate.id);
      const sourceIds = mediaSourceIds(media);
      if (sourceMediaIds.every((sourceId) => sourceIds.includes(sourceId))) {
        matches.push(media);
      }
    }
    return matches.length >= expectedCount ? matches : null;
  }, 30000);
}

export async function getMarkers(page: Page): Promise<Marker[]> {
  return apiJSON(page, '/api/markers');
}

export async function addMarkerToMedia(page: Page, mediaId: number, markerId: number) {
  return apiJSON(page, `/api/media/${mediaId}/markers/${markerId}`, { method: 'POST' });
}

export async function removeMarkerFromMedia(page: Page, mediaId: number, markerId: number) {
  return apiJSON(page, `/api/media/${mediaId}/markers/${markerId}`, { method: 'DELETE' });
}

export async function bulkMarkerOperation(page: Page, mediaIds: number[], markerId: number, add = true) {
  return apiJSON(page, '/api/media/batch/markers', {
    method: 'POST',
    data: { media_ids: mediaIds, marker_id: markerId, add },
  } as any);
}

export async function createBoard(page: Page, name: string, projectId?: number): Promise<{ id: number }> {
  return apiJSON(page, '/api/boards', {
    method: 'POST',
    data: { name, project_id: projectId ?? null },
  } as any);
}

export async function listBoards(page: Page, projectId?: number): Promise<Board[]> {
  const suffix = projectId == null ? '' : `?project_id=${projectId}`;
  return apiJSON(page, `/api/boards${suffix}`);
}

export async function updateBoard(page: Page, boardId: number, data: Record<string, unknown>): Promise<Board> {
  return apiJSON(page, `/api/boards/${boardId}`, { method: 'PUT', data } as any);
}

export async function deleteBoard(page: Page, boardId: number) {
  return apiJSON(page, `/api/boards/${boardId}`, { method: 'DELETE' });
}

export async function restoreBoard(page: Page, boardId: number): Promise<Board> {
  return apiJSON(page, `/api/boards/${boardId}/restore`, { method: 'POST' });
}

export async function createBoardSection(page: Page, boardId: number, name: string): Promise<BoardSection> {
  return apiJSON(page, `/api/boards/${boardId}/sections`, {
    method: 'POST',
    data: { name },
  } as any);
}

export async function updateBoardSection(page: Page, sectionId: number, data: Record<string, unknown>): Promise<BoardSection> {
  return apiJSON(page, `/api/boards/sections/${sectionId}`, { method: 'PUT', data } as any);
}

export async function deleteBoardSection(page: Page, sectionId: number) {
  return apiJSON(page, `/api/boards/sections/${sectionId}`, { method: 'DELETE' });
}

export async function reorderBoardSections(page: Page, boardId: number, sectionIds: number[]) {
  return apiJSON(page, `/api/boards/${boardId}/sections/reorder`, {
    method: 'POST',
    data: { section_ids: sectionIds },
  } as any);
}

export async function addMediaToBoard(page: Page, boardId: number, mediaIds: number[]) {
  return apiJSON(page, `/api/boards/${boardId}/items`, {
    method: 'POST',
    data: { media_ids: mediaIds, section_id: null },
  } as any);
}

export async function removeMediaFromBoardSection(page: Page, sectionId: number, mediaId: number) {
  return apiJSON(page, `/api/boards/sections/${sectionId}/items/${mediaId}`, { method: 'DELETE' });
}

export async function moveBoardItem(
  page: Page,
  boardId: number,
  mediaId: number,
  fromSectionId: number,
  toSectionId: number,
  targetIndex: number,
) {
  return apiJSON(page, `/api/boards/${boardId}/items/move`, {
    method: 'POST',
    data: {
      media_id: mediaId,
      from_section_id: fromSectionId,
      to_section_id: toSectionId,
      target_index: targetIndex,
    },
  } as any);
}

export async function bulkRemoveBoardItems(page: Page, boardId: number, mediaIds: number[]) {
  return apiJSON(page, `/api/boards/${boardId}/items/bulk-remove`, {
    method: 'POST',
    data: { media_ids: mediaIds },
  } as any);
}

export async function bulkMoveBoardItems(page: Page, boardId: number, mediaIds: number[], toSectionId: number) {
  return apiJSON(page, `/api/boards/${boardId}/items/bulk-move`, {
    method: 'POST',
    data: { media_ids: mediaIds, to_section_id: toSectionId },
  } as any);
}

export async function getBoard(page: Page, boardId: number): Promise<{
  id: number;
  sections: { id: number; items: MediaItem[]; item_count: number }[];
}> {
  return apiJSON(page, `/api/boards/${boardId}`);
}

export async function trashMedia(page: Page, mediaId: number) {
  return apiJSON(page, `/api/media/${mediaId}`, { method: 'DELETE' });
}

export async function bulkTrashMedia(page: Page, mediaIds: number[]) {
  return apiJSON(page, '/api/media/batch/delete', {
    method: 'POST',
    data: { media_ids: mediaIds },
  } as any);
}

export async function listTrash(page: Page, params: Record<string, string | number | boolean> = {}): Promise<MediaItem[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  const media = await apiJSON<{ items: MediaItem[] }>(page, `/api/trash${suffix}`);
  return media.items;
}

export async function restoreMedia(page: Page, mediaId: number) {
  return apiJSON(page, `/api/trash/${mediaId}/restore`, { method: 'POST' });
}

export async function bulkRestoreMedia(page: Page, mediaIds: number[]) {
  return apiJSON(page, '/api/trash/batch/restore', {
    method: 'POST',
    data: { media_ids: mediaIds },
  } as any);
}

export async function uploadMediaViaUI(page: Page, filePath: string, projectId?: number): Promise<MediaItem> {
  const suffix = projectId == null ? '' : `?project_id=${projectId}`;
  await page.goto(`/upload${suffix}`);
  await waitForShell(page);
  await expect(page.getByText('Drag files here to upload')).toBeVisible({ timeout: 30000 });

  const responsePromise = page.waitForResponse((response) => (
    response.url().includes('/generate/upload-bulk') && response.request().method() === 'POST'
  ));
  await page.locator('input[type="file"]').setInputFiles(filePath);
  const response = await responsePromise;
  if (!response.ok()) {
    throw new Error(`Upload failed with ${response.status()}: ${await response.text()}`);
  }
  const body = await response.json();
  const uploaded = body.results?.find((item: any) => item.status === 'success' && item.media_id);
  if (!uploaded) {
    throw new Error(`Upload did not return a successful media item: ${JSON.stringify(body)}`);
  }

  await expect(page.getByText('1 uploaded')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('img').first()).toBeVisible({ timeout: 30000 });
  return getMedia(page, uploaded.media_id);
}

export async function createChat(page: Page, name: string, projectId?: number): Promise<Chat> {
  return apiJSON(page, '/api/chats', {
    method: 'POST',
    data: { name, project_id: projectId ?? null },
  } as any);
}

export async function listChats(page: Page, options: { includeDeleted?: boolean; projectId?: number } = {}) {
  const query = new URLSearchParams({ page: '1', page_size: '50' });
  if (options.includeDeleted) query.set('include_deleted', 'true');
  if (options.projectId != null) query.set('project_id', String(options.projectId));
  return apiJSON<{ items: Chat[]; total: number }>(page, `/api/chats?${query.toString()}`);
}

export async function getChat(page: Page, chatId: number): Promise<Chat> {
  return apiJSON(page, `/api/chats/${chatId}`);
}

export async function updateChat(page: Page, chatId: number, data: Record<string, unknown>): Promise<Chat> {
  return apiJSON(page, `/api/chats/${chatId}`, { method: 'PATCH', data } as any);
}

export async function deleteChat(page: Page, chatId: number) {
  return apiJSON(page, `/api/chats/${chatId}`, { method: 'DELETE' });
}

export async function restoreChat(page: Page, chatId: number): Promise<Chat> {
  return apiJSON(page, `/api/chats/${chatId}/restore`, { method: 'POST' });
}

export async function batchDeleteChats(page: Page, ids: number[]) {
  return apiJSON(page, '/api/chats/batch/delete', {
    method: 'POST',
    data: { ids },
  } as any);
}

export async function batchRestoreChats(page: Page, ids: number[]) {
  return apiJSON(page, '/api/chats/batch/restore', {
    method: 'POST',
    data: { ids },
  } as any);
}

export async function listChatItems(page: Page, chatId: number): Promise<ChatItem[]> {
  const response = await apiJSON<{ items: ChatItem[] }>(page, `/api/chats/${chatId}/items?visible_limit=500`);
  return response.items;
}

export async function waitForChatItem(
  page: Page,
  chatId: number,
  predicate: (item: ChatItem) => boolean,
): Promise<ChatItem> {
  return waitFor(async () => {
    const items = await listChatItems(page, chatId);
    return items.find(predicate) ?? null;
  }, 30000);
}

export async function sendChatMessage(page: Page, message: string) {
  const input = page.getByRole('textbox', { name: 'Type a message...' });
  await expect(input).toBeVisible({ timeout: 30000 });
  await expect(input).toBeEnabled({ timeout: 30000 });

  // A blind fill+Enter is racy: the composer's send handler silently no-ops while
  // the chat-model list is still resolving (sendMessage() returns early on
  // isChatModelUnavailable), leaving the text in the box and nothing sent — which
  // shows up downstream as the user message never appearing. Retry the submit
  // until it's actually accepted. The composer clears messageInput synchronously
  // once a send goes through, so an emptied box is the signal that it landed.
  await expect(async () => {
    if ((await input.inputValue()) !== message) {
      await input.fill(message);
      await expect(input).toHaveValue(message);
    }
    await input.press('Enter');
    await expect(input).toHaveValue('', { timeout: 2000 });
  }).toPass({ timeout: 30000 });
}

export async function waitFor<T>(check: () => Promise<T | null>, timeoutMs: number, label = 'condition'): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const suffix = lastError instanceof Error ? `; last_error=${lastError.message}` : '';
  throw new Error(`Timed out waiting for ${label} after ${timeoutMs}ms${suffix}`);
}

function promptInput(page: Page) {
  return page.locator('.cm-content[contenteditable="true"]').first();
}

async function continueWithoutAccountIfNeeded(page: Page) {
  const shell = page.getByText('All Assets', { exact: true }).first();
  const skip = page.getByText('Continue without an account', { exact: true }).first();
  const deadline = Date.now() + 30000;

  while (Date.now() < deadline) {
    if (await shell.isVisible({ timeout: 250 }).catch(() => false)) return;
    if (await skip.isVisible({ timeout: 250 }).catch(() => false)) {
      await skip.click();
      await page.getByRole('button', { name: 'Continue without account' }).first().click();
      await expect(shell).toBeVisible({ timeout: 30000 });
      return;
    }
  }
  throw new Error('Timed out waiting for either onboarding or the application shell');
}
