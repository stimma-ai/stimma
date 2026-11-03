import { expect, test, type Page, type Browser } from '@playwright/test';
import { TEST_T2I_TOOL_ID, apiJSON } from '../helpers/app';
import { openDesktopClient, type WorkspaceSnapshot } from '../helpers/lockstep';
import { settleAnyViewport } from '../helpers/viewport';

async function newProfile(page: Page): Promise<{ id: string }> {
  await page.goto('/browse');
  await settleAnyViewport(page);
  const created = await apiJSON<{ id?: string; profile?: { id: string } }>(page, '/api/settings/profiles', {
    method: 'POST',
    data: JSON.stringify({ name: `Migrate ${Date.now().toString(36)}` }),
  } as RequestInit);
  const id = created.id ?? created.profile!.id;
  // A new profile is usable once the config reload behind it has landed.
  await expect.poll(async () => (await page.request.get('/api/workspace', { headers: { 'X-Profile-ID': id } })).ok()).toBe(true);
  await expect.poll(async () => JSON.stringify(await apiJSON(page, '/api/profiles'))).toContain(id);
  return { id };
}

function legacyTab(instance: string, extra: Record<string, unknown> = {}) {
  const feedScope = `${TEST_T2I_TOOL_ID.replace(/:/g, '_')}__i_${instance}`;
  return {
    id: `tool:${TEST_T2I_TOOL_ID}:i:${instance}`,
    type: 'tool',
    entityId: TEST_T2I_TOOL_ID,
    pinned: false,
    displayOrder: Number(instance),
    displayName: 'Test Model',
    instanceId: instance,
    feedScope,
    lastActivatedAt: 1000,
    ...extra,
  };
}

/** A desktop that has been using this profile: its local storage, before boot. */
async function seedLegacyDesktop(page: Page, profileId: string, tabs: any[], extra: Record<string, string> = {}) {
  await page.addInitScript(({ profileId, tabs, extra }) => {
    if (sessionStorage.getItem('seeded')) return;
    sessionStorage.setItem('seeded', '1');
    const bundle = localStorage.getItem('stimma_bundle_id');
    const sandbox = localStorage.getItem('stimma_sandbox');
    const p = `stimma_${bundle}_${sandbox}_${profileId}_`;
    localStorage.setItem('profileId', profileId);
    localStorage.setItem(`${p}workspace_tabs`, JSON.stringify(tabs));
    for (const [key, value] of Object.entries(extra)) localStorage.setItem(`${p}${key}`, value);
  }, { profileId, tabs, extra });
}

function snapshotOf(page: Page, profileId: string): Promise<WorkspaceSnapshot> {
  return apiJSON<WorkspaceSnapshot>(page, '/api/workspace', { headers: { 'X-Profile-ID': profileId } } as RequestInit);
}

async function bootedDesktop(browser: Browser, profileId: string, tabs: any[], extra: Record<string, string> = {}) {
  const page = await openDesktopClient(browser);
  await page.goto('/browse');
  await seedLegacyDesktop(page, profileId, tabs, extra);
  await page.goto('/browse');
  await settleAnyViewport(page);
  return page;
}

const STATE_KEY = (instance: string) => `tool_${TEST_T2I_TOOL_ID.replace(/:/g, '_')}__i_${instance}_state`;

test.describe('carrying a local workspace onto the server', () => {
  test('the first desktop with a workspace claims it, and it survives intact', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    const desktop = await bootedDesktop(browser, id, [
      legacyTab('7', { customName: 'Hero shots', pinned: true }),
      legacyTab('8'),
    ], {
      [STATE_KEY('7')]: JSON.stringify({ prompt: 'carried over', steps: 12 }),
      [STATE_KEY('99')]: JSON.stringify({ prompt: 'from a closed tab' }),
      sidebar_width: '400',
    });

    await expect.poll(async () => (await snapshotOf(desktop, id)).migration.claimed).toBe(true);
    const { docs } = await snapshotOf(desktop, id);
    const byKey = new Map(docs.map(d => [d.key, d.value]));
    expect(byKey.get(`tool:${TEST_T2I_TOOL_ID}:i:7`).customName).toBe('Hero shots');
    expect(byKey.get(`tool:${TEST_T2I_TOOL_ID}:i:7`).pinned).toBe(true);
    expect(byKey.has(`tool:${TEST_T2I_TOOL_ID}:i:8`)).toBe(true);
    expect(byKey.get(STATE_KEY('7'))).toEqual({ prompt: 'carried over', steps: 12 });
    expect(byKey.has(STATE_KEY('99')), 'a closed tab\'s state stays behind').toBe(false);
    expect(byKey.has('sidebar_width'), 'device state stays behind').toBe(false);

    // Local copies are left alone, so a downgrade still has its workspace.
    const local = await desktop.evaluate((id) => {
      const key = Object.keys(localStorage).find(k => k.endsWith(`${id}_workspace_tabs`))!;
      return JSON.parse(localStorage.getItem(key)!).length;
    }, id);
    expect(local).toBe(2);
    await desktop.context().close();
  });

  test('tabs made before the desktop arrives are kept alongside its workspace', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    // A phone with nothing local: it makes a tab but can't claim anything.
    await page.evaluate((id) => localStorage.setItem('profileId', id), id);
    await page.goto(`/tools/${TEST_T2I_TOOL_ID}?project_id=0&instance=fromphone`);
    await settleAnyViewport(page);
    await expect.poll(async () => (await snapshotOf(page, id)).docs.some(d => d.key.endsWith(':i:fromphone')), { timeout: 15000 }).toBe(true);
    expect((await snapshotOf(page, id)).migration.claimed).toBe(false);

    const desktop = await bootedDesktop(browser, id, [legacyTab('7', { customName: 'From the desk' })]);
    await expect.poll(async () => (await snapshotOf(desktop, id)).migration.claimed).toBe(true);
    const tabs = (await snapshotOf(desktop, id)).docs.filter(d => d.namespace === 'tab');
    expect(tabs.map(d => d.value.customName)).toContain('From the desk');
    expect(tabs.map(d => d.key)).toContain(`tool:${TEST_T2I_TOOL_ID}:i:fromphone`);
    await desktop.context().close();
  });

  test('a second desktop is archived and takes on the shared workspace', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    const first = await bootedDesktop(browser, id, [legacyTab('1', { customName: 'First' })]);
    await expect.poll(async () => (await snapshotOf(first, id)).migration.claimed).toBe(true);

    const second = await bootedDesktop(browser, id, [legacyTab('2', { customName: 'Second' })]);
    await expect.poll(() => second.evaluate((id) =>
      Object.keys(localStorage).filter(k => k.endsWith(`${id}_workspace_migrated`)).map(k => localStorage.getItem(k))[0], id))
      .toBe('archived');
    const names = (await snapshotOf(second, id)).docs.filter(d => d.namespace === 'tab').map(d => d.value.customName);
    expect(names).toContain('First');
    expect(names).not.toContain('Second');
    await first.context().close();
    await second.context().close();
  });

  test('a new install with nothing local claims nothing', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    const fresh = await bootedDesktop(browser, id, []);
    await fresh.waitForTimeout(1500);
    expect((await snapshotOf(fresh, id)).migration.claimed).toBe(false);
    await fresh.context().close();
  });

  test('tabs for things that no longer exist are dropped', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    const desktop = await bootedDesktop(browser, id, [
      legacyTab('7'),
      { id: 'chat:999999', type: 'chat', entityId: '999999', pinned: false, displayOrder: 9, displayName: 'Gone' },
    ]);
    await expect.poll(async () => (await snapshotOf(desktop, id)).migration.claimed).toBe(true);
    const keys = (await snapshotOf(desktop, id)).docs.filter(d => d.namespace === 'tab').map(d => d.key);
    expect(keys).not.toContain('chat:999999');
    expect(keys).toContain(`tool:${TEST_T2I_TOOL_ID}:i:7`);
    await desktop.context().close();
  });

  test('an upload that fails is retried on the next launch', async ({ page, browser }) => {
    const { id } = await newProfile(page);
    const desktop = await openDesktopClient(browser);
    await desktop.goto('/browse');
    await seedLegacyDesktop(desktop, id, [legacyTab('5', { customName: 'Retried' })]);
    await desktop.route('**/api/workspace/migrate', route => route.abort());
    await desktop.goto('/browse');
    await settleAnyViewport(desktop);
    expect((await snapshotOf(desktop, id)).migration.claimed).toBe(false);

    await desktop.unroute('**/api/workspace/migrate');
    await desktop.reload();
    await settleAnyViewport(desktop);
    await expect.poll(async () => (await snapshotOf(desktop, id)).migration.claimed).toBe(true);
    await desktop.context().close();
  });
});
