import { expect, test, type Page } from '@playwright/test';
import { TEST_T2I_TOOL_ID, apiJSON, submitGeneration } from '../helpers/app';
import {
  SETTLE_MS,
  countWrites,
  openDesktopClient,
  promptEditor,
  readWorkspace,
  toolInstanceOf,
  workspaceTabs,
} from '../helpers/lockstep';
import { settleAnyViewport } from '../helpers/viewport';

async function openToolTab(page: Page, instance: string) {
  await page.goto(`/tools/${TEST_T2I_TOOL_ID}?project_id=0&instance=${instance}`);
  await settleAnyViewport(page);
  await expect(promptEditor(page)).toBeVisible({ timeout: 30000 });
}

/** Open one tool tab on both clients. */
async function sameToolTab(desktop: Page, phone: Page) {
  const instance = `lockstep${Date.now().toString(36)}`;
  await openToolTab(desktop, instance);
  await expect.poll(async () => (await workspaceTabs(desktop)).some(t => t.instanceId === instance)).toBe(true);
  await openToolTab(phone, instance);
  return instance;
}

test.describe('two clients share one workspace', () => {
  // Every test here opens a second browser context. The lane serves the app
  // from Vite's dev server, so a fresh context loads ~900 unbundled modules:
  // about 20 s on a CI runner before any assertion (seen in traces). With
  // reloads on both clients, the phone lane's 30 s budget is too tight.
  test.describe.configure({ timeout: 60000 });

  test('a tool tab opened on one client appears on the other, without moving it', async ({ page: phone, browser }) => {
    // This case cold-loads both app clients. The first ToolView transform
    // alone has taken 19s on CI; leave room for both startups and assertions.
    test.setTimeout(60000);
    const desktop = await openDesktopClient(browser);
    await phone.goto('/browse');
    await settleAnyViewport(phone);
    const phoneUrl = phone.url();

    await openToolTab(desktop, 'opened1');

    const drawer = phone.locator('.navigation-sidebar');
    await phone.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(drawer.getByText('Test Text-to-Image').first()).toBeVisible();
    expect(phone.url()).toBe(phoneUrl);
    await desktop.context().close();
  });

  test('pinning, renaming and reordering on a client that has reloaded reach the other', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    await desktop.reload();
    await expect(promptEditor(desktop)).toBeVisible({ timeout: 30000 });
    const tabOf = async () => (await workspaceTabs(phone)).find(t => t.instanceId === instance)!;

    const row = desktop.locator('.navigation-sidebar').getByRole('button', { name: /Test Text-to-Image/ }).first();
    await row.click({ button: 'right' });
    await desktop.getByRole('button', { name: 'Pin', exact: true }).click();
    await expect.poll(async () => (await tabOf()).pinned).toBe(true);

    await phone.reload();
    await expect(promptEditor(phone)).toBeVisible({ timeout: 30000 });
    // A detail screen's left button is Back; the drawer opens from the hub it returns to.
    await phone.getByRole('button', { name: 'Back', exact: true }).click();
    await phone.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(phone.locator('.navigation-sidebar').getByText('Pinned', { exact: true })).toBeVisible();

    await row.click({ button: 'right' });
    await desktop.getByRole('button', { name: 'Unpin', exact: true }).click();
    await expect.poll(async () => (await tabOf()).pinned).toBe(false);
    await desktop.context().close();
  });

  test('tool edits follow live, different fields both win, the watcher stays silent', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    const phoneWrites = countWrites(phone);
    const desktopWrites = countWrites(desktop);
    await desktop.waitForTimeout(SETTLE_MS);
    phoneWrites.reset();
    desktopWrites.reset();

    // Desktop types; the phone only watches.
    await promptEditor(desktop).click();
    await desktop.keyboard.type('a lighthouse at dusk');
    await expect(promptEditor(phone)).toHaveText('a lighthouse at dusk');
    await desktop.waitForTimeout(SETTLE_MS);
    expect(desktopWrites.count).toBeGreaterThan(0);
    expect(phoneWrites.count, 'a watching client must not write').toBe(0);

    const stateKey = (await readWorkspace(desktop)).docs.find(d => d.key.includes(`__i_${instance}_state`))!;
    expect(stateKey.value.prompt).toBe('a lighthouse at dusk');
    await desktop.context().close();
  });

  test('a field being typed in is not overwritten until the cursor leaves', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    await sameToolTab(desktop, phone);

    await promptEditor(phone).click();
    await phone.keyboard.type('phone draft');
    await expect(promptEditor(desktop)).toHaveText('phone draft');

    // The desktop's cursor is in the field when the phone's next edit lands.
    await promptEditor(desktop).click();
    await phone.keyboard.type(' continued');
    await desktop.waitForTimeout(SETTLE_MS);
    await expect(promptEditor(desktop)).toHaveText('phone draft');

    await desktop.evaluate(() => (document.activeElement as HTMLElement).blur());
    await expect(promptEditor(desktop)).toHaveText('phone draft continued');
    await desktop.context().close();
  });

  test('a field held back while focused isn\'t sent over what arrived', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    const stateDoc = async () => (await readWorkspace(desktop)).docs.find(d => d.key.includes(`__i_${instance}_state`));
    await promptEditor(desktop).click();
    await desktop.keyboard.type('desktop start');
    await expect.poll(async () => (await stateDoc())?.value.prompt).toBe('desktop start');
    await desktop.waitForTimeout(800);

    const key = (await stateDoc())!.key;
    const other = (set: object) => apiJSON(desktop, '/api/workspace/docs', {
      method: 'POST',
      data: JSON.stringify({ origin: 'other-client', ops: [{ namespace: 'kv', key, set }] }),
    } as RequestInit);
    await other({ prompt: 'from elsewhere', steps: 11 });
    await other({ steps: 12 });
    await desktop.waitForTimeout(SETTLE_MS);

    expect((await stateDoc())!.value).toMatchObject({ prompt: 'from elsewhere', steps: 12 });
    await expect(promptEditor(desktop)).toHaveText('desktop start');
    await desktop.keyboard.type(' typed');
    await expect.poll(async () => (await stateDoc())?.value.prompt).toBe('desktop start typed');
    await desktop.context().close();
  });

  test('typing just as another client\'s change lands isn\'t lost', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    const stateDoc = async () => (await readWorkspace(desktop)).docs.find(d => d.key.includes(`__i_${instance}_state`));
    await promptEditor(desktop).click();
    await desktop.keyboard.type('start');
    await expect.poll(async () => (await stateDoc())?.value.prompt).toBe('start');
    await desktop.waitForTimeout(800);
    const key = (await stateDoc())!.key;

    // Keystrokes through the whole window while changes arrive, overlapping.
    const other = (steps: number) => apiJSON(desktop, '/api/workspace/docs', {
      method: 'POST',
      data: JSON.stringify({ origin: 'other-client', ops: [{ namespace: 'kv', key, set: { steps } }] }),
    } as RequestInit);
    await Promise.all([
      other(20).then(() => other(21)),
      desktop.keyboard.type(' typed on', { delay: 15 }),
    ]);

    await expect.poll(async () => (await stateDoc())?.value.prompt, { timeout: 10000 }).toBe('start typed on');
    expect((await stateDoc())!.value.steps).toBe(21);
    await desktop.context().close();
  });

  test('an unsaved edit here and a change from another client both survive', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    const stateKey = async () => (await readWorkspace(desktop)).docs.find(d => d.key.includes(`__i_${instance}_state`));
    await promptEditor(desktop).click();
    await desktop.keyboard.type('first');
    await expect.poll(async () => (await stateKey())?.value.prompt).toBe('first');

    // Another client changes a different field while this one's typing is still
    // waiting on its debounce.
    await desktop.keyboard.type(' more');
    await apiJSON(desktop, '/api/workspace/docs', {
      method: 'POST',
      data: JSON.stringify({ origin: 'other-client', ops: [{ namespace: 'kv', key: (await stateKey())!.key, set: { steps: 37 } }] }),
    } as RequestInit);

    await expect.poll(async () => (await stateKey())?.value.prompt).toBe('first more');
    await desktop.waitForTimeout(SETTLE_MS);
    expect((await stateKey())!.value.steps, 'the other client\'s change was reverted').toBe(37);
    await desktop.context().close();
  });

  test('a job started on one client shows in the other client\'s feed', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);

    await expect(phone.getByText('Make something wonderful')).toBeVisible();
    await submitGeneration(desktop, 'made on the desktop');

    await expect.poll(async () => {
      const scope = (await workspaceTabs(desktop)).find(t => t.instanceId === instance)?.feedScope;
      const { jobs } = await apiJSON<{ jobs: any[] }>(desktop, `/api/generate/jobs?feed_scope=${encodeURIComponent(scope)}`);
      return jobs.length;
    }, { timeout: 30000 }).toBeGreaterThan(0);
    // Live, with no reload on the phone.
    await expect(phone.getByText('Make something wonderful')).toBeHidden({ timeout: 30000 });
    await desktop.context().close();
  });

  test('closing the tab another client is viewing moves it on, and it can come back', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);
    const tab = (await workspaceTabs(desktop)).find(t => t.instanceId === instance)!;

    await apiJSON(desktop, '/api/workspace/docs', {
      method: 'POST',
      data: JSON.stringify({ origin: 'other-client', ops: [{ namespace: 'tab', key: tab.id, deleted: true }] }),
    } as RequestInit);

    await expect(phone).not.toHaveURL(new RegExp(`instance=${instance}`), { timeout: 10000 });
    await expect(phone.getByText('Closed on another device')).toBeVisible();
    await phone.getByRole('button', { name: 'Reopen' }).click();
    await expect(phone).toHaveURL(new RegExp(`instance=${instance}`));
    await expect.poll(async () => (await workspaceTabs(desktop)).some(t => t.id === tab.id), { timeout: 15000 }).toBe(true);
    await desktop.context().close();
  });

  test('a client that was offline catches up, and what it did meanwhile arrives', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    const instance = await sameToolTab(desktop, phone);

    await phone.context().setOffline(true);
    await promptEditor(desktop).click();
    await desktop.keyboard.type('while the phone was away');
    await desktop.waitForTimeout(SETTLE_MS);
    await phone.context().setOffline(false);

    await expect(promptEditor(phone)).toHaveText('while the phone was away', { timeout: 45000 });
    const state = (await readWorkspace(desktop)).docs.find(d => d.key.includes(`__i_${instance}_state`))!;
    expect(state.value.prompt).toBe('while the phone was away');
    await desktop.context().close();
  });

  test('what stays with the device does not cross clients', async ({ page: phone, browser }) => {
    const desktop = await openDesktopClient(browser);
    await desktop.goto('/browse');
    await settleAnyViewport(desktop);
    const keysBefore = new Set((await readWorkspace(desktop)).docs.map(d => d.key));
    await phone.goto('/browse?viewport=compact');
    await settleAnyViewport(phone);
    for (const key of keysBefore) {
      expect(key, 'device state must not reach the server').not.toMatch(/^(sidebar|media_playback|browse_filters|last_route|pin_cache|theme)/);
    }
    await desktop.context().close();
  });
});
