import { Page, Locator } from '@playwright/test';

const BACKEND_PORT = process.env.STIMMA_BACKEND_PORT || '9191';
const API_BASE = `http://localhost:${BACKEND_PORT}`;
const PROFILE_ID = 'profile-ebAzF4';

function apiHeaders() {
  return { 'X-Profile-ID': PROFILE_ID };
}

// ── Navigation ──────────────────────────────────────────────────────────

export async function goToTrash(page: Page) {
  await page.goto('/trash');
  await page.getByRole('heading', { name: 'Trash', level: 1 }).waitFor({ state: 'visible', timeout: 15000 });
}

export async function goToCollections(page: Page) {
  await page.goto('/collections');
  await page.waitForLoadState('networkidle');
}

export async function goToCollection(page: Page, id: string) {
  await page.goto(`/collections/${id}`);
  await page.locator('.collection-detail-view').waitFor({ state: 'visible', timeout: 15000 });
}

// ── Media Grid ──────────────────────────────────────────────────────────

export function getMediaItems(page: Page): Locator {
  return page.locator('.grid-cell:not(.grid-cell-placeholder)');
}

export async function ensureMediaExists(page: Page, minCount = 1) {
  await getMediaItems(page).first().waitFor({ state: 'visible', timeout: 15000 });
  const count = await getMediaItems(page).count();
  if (count < minCount) {
    throw new Error(`Expected at least ${minCount} media items, found ${count}`);
  }
  return count;
}

// ── Multi-Select ────────────────────────────────────────────────────────

export async function ctrlClickItem(page: Page, index: number) {
  const item = getMediaItems(page).nth(index);
  await item.waitFor({ state: 'visible', timeout: 10000 });
  await item.click({ modifiers: ['Meta'] });
}

export async function selectItems(page: Page, indices: number[]) {
  for (const index of indices) {
    await ctrlClickItem(page, index);
  }
}

export function getActionBar(page: Page): Locator {
  return page.locator('.multi-select-action-bar');
}

export async function waitForActionBar(page: Page) {
  await getActionBar(page).waitFor({ state: 'visible', timeout: 10000 });
}

export async function getSelectedCount(page: Page): Promise<string> {
  const countEl = page.locator('.count-text');
  await countEl.waitFor({ state: 'visible', timeout: 5000 });
  return (await countEl.textContent()) ?? '';
}

// ── Marker Helpers (FilterBar) ──────────────────────────────────────────

export function getFilterBarMarkerButton(page: Page, markerName: string): Locator {
  return page.locator(`button[title="${markerName}"]`).filter({ has: page.locator('.icon-container') });
}

export async function clickFilterBarMarker(page: Page, markerName: string) {
  await getFilterBarMarkerButton(page, markerName).click();
}

export async function isMarkerFilterPositive(page: Page, markerName: string): Promise<boolean> {
  const btn = getFilterBarMarkerButton(page, markerName);
  const classes = (await btn.getAttribute('class')) ?? '';
  return classes.includes('bg-blue-500');
}

export async function isMarkerFilterNegative(page: Page, markerName: string): Promise<boolean> {
  const btn = getFilterBarMarkerButton(page, markerName);
  const classes = (await btn.getAttribute('class')) ?? '';
  return classes.includes('bg-red-500');
}

// ── Marker Helpers (Action Bar) ─────────────────────────────────────────

export function getActionBarMarkerButtons(page: Page): Locator {
  return getActionBar(page).locator('button.marker-button');
}

export async function clickActionBarMarker(page: Page, markerName: string) {
  const addBtn = getActionBar(page).locator(`button[title="Add ${markerName}"]`);
  const removeBtn = getActionBar(page).locator(`button[title="Remove ${markerName}"]`);
  if (await removeBtn.isVisible()) {
    await removeBtn.click();
  } else {
    await addBtn.click();
  }
}

export async function isActionBarMarkerActive(page: Page, markerName: string): Promise<boolean> {
  const btn = getActionBar(page).locator(`button.marker-button.active[title="Remove ${markerName}"]`);
  return btn.isVisible();
}

// ── API Shortcuts ───────────────────────────────────────────────────────

export async function getMarkersViaApi(page: Page): Promise<Array<{ id: number; name: string; icon_svg: string; color: string }>> {
  const resp = await page.request.get(`${API_BASE}/api/markers`, { headers: apiHeaders() });
  if (!resp.ok()) return [];
  const data = await resp.json();
  // API returns array directly
  return Array.isArray(data) ? data : (data.markers ?? []);
}

export async function getMediaIdsViaApi(page: Page, count = 5): Promise<number[]> {
  const resp = await page.request.get(`${API_BASE}/api/media?page_size=${count}`, { headers: apiHeaders() });
  const data = await resp.json();
  const items = data.items ?? [];
  return items.map((item: { id: number }) => item.id);
}

export async function createCollectionViaApi(page: Page, name: string): Promise<string> {
  const resp = await page.request.post(`${API_BASE}/api/collections`, {
    headers: apiHeaders(),
    data: { name },
  });
  const data = await resp.json();
  return String(data.id);
}

export async function deleteCollectionViaApi(page: Page, id: string) {
  await page.request.delete(`${API_BASE}/api/collections/${id}`, { headers: apiHeaders() });
}

export async function addMediaToCollectionViaApi(page: Page, mediaIds: number[], collectionId: string) {
  await page.request.post(`${API_BASE}/api/collections/batch/media`, {
    headers: apiHeaders(),
    data: { media_ids: mediaIds, collection_id: parseInt(collectionId), add: true },
  });
}

export async function moveToTrashViaApi(page: Page, mediaIds: number[]) {
  await page.request.post(`${API_BASE}/api/media/batch/delete`, {
    headers: apiHeaders(),
    data: { media_ids: mediaIds },
  });
}

export async function restoreFromTrashViaApi(page: Page, mediaIds: number[]) {
  await page.request.post(`${API_BASE}/api/trash/batch/restore`, {
    headers: apiHeaders(),
    data: { media_ids: mediaIds },
  });
}
