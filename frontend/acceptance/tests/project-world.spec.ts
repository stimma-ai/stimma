import { expect, test } from '../helpers/testbed';
import type { Page } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  addMediaToProject,
  apiJSON,
  chooseContext,
  createBoard,
  createChat,
  createProject,
  expectContext,
  generateMedia,
  getChat,
  listMedia,
  openToolById,
  submitGeneration,
  TEST_I2I_TOOL_ID,
  waitFor,
  waitForShell,
} from '../helpers/app';

// A project is its own small world: whatever is made, uploaded, exploded or
// cloned in project P lands in P, the top level lists only unfiled items, and
// navigation follows the item's project. Every case here runs across two
// projects (P and Q) and the top level, with the fake tool provider.

type Media = { id: number; asset_id?: number };

const fixturePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../public/logo.png');
const sidebar = (page: Page) => page.locator('.navigation-sidebar');
const tile = (page: Page, media: Media) => page.getByTestId(`media-grid-item-${media.asset_id ?? media.id}`);
// Letters and digits only: prompts are matched by full-text search.
const stamp = () => `${Date.now()}${Math.random().toString(36).slice(2, 6)}`;

async function uniqueImage(testInfo: { outputPath: (...segments: string[]) => string }) {
  const bytes = await readFile(fixturePath);
  const target = testInfo.outputPath(`ref-${stamp()}.png`);
  await writeFile(target, Buffer.concat([bytes, Buffer.from(`\nproject-world-${stamp()}`)]));
  return target;
}

async function projectsOf(page: Page, mediaId: number): Promise<number[]> {
  const projects = await apiJSON<Array<{ id: number }>>(page, `/api/media/${mediaId}/projects`);
  return projects.map(p => p.id);
}

async function inProject(page: Page, projectId: number, mediaId: number) {
  return (await listMedia(page, { page: 1, page_size: 200, project_id: projectId })).some(m => m.id === mediaId);
}

async function twoProjects(page: Page) {
  const tag = stamp();
  const p = await createProject(page, `World P ${tag}`);
  const q = await createProject(page, `World Q ${tag}`);
  return { p, q };
}

/** Right-clicks a grid tile and returns the open context menu. */
async function openTileMenu(page: Page, media: Media) {
  const item = tile(page, media);
  await expect(item).toBeVisible({ timeout: 30000 });
  await item.click({ button: 'right' });
  const menu = page.getByRole('button', { name: 'Send to Tool', exact: true }).filter({ visible: true });
  await expect(menu.first()).toBeVisible();
}

function dropMedia(mediaId: number) {
  return (element: Element, id: number) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.setData('application/x-media-id', String(id));
    element.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer }));
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
  };
}

test.describe('project world', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
  });

  test('a reference uploaded into a project tool slot or chat composer lands in that project', async ({ page }, testInfo) => {
    const { p, q } = await twoProjects(page);

    await openToolById(page, TEST_I2I_TOOL_ID, p.id);
    const slotUpload = page.waitForResponse(r => r.url().includes('/api/generate/upload-reference') && r.request().method() === 'POST');
    await page.locator('[data-drop-zone="media-picker-image"]').locator('input[type="file"]').first()
      .setInputFiles(await uniqueImage(testInfo));
    const slotResponse = await slotUpload;
    expect(slotResponse.ok()).toBe(true);
    const slotMediaId = (await slotResponse.json()).media_id as number;
    expect(await projectsOf(page, slotMediaId)).toEqual([p.id]);

    const chat = await createChat(page, `World composer ${stamp()}`, q.id);
    await page.goto(`/chat/${chat.id}`);
    await expectContext(page, q.name);
    const composerUpload = page.waitForResponse(r => r.url().includes('/api/generate/upload-reference') && r.request().method() === 'POST');
    await page.locator('input[type="file"][accept="image/jpeg,image/png,image/webp"]').last()
      .setInputFiles(await uniqueImage(testInfo));
    const composerResponse = await composerUpload;
    expect(composerResponse.ok()).toBe(true);
    const composerMediaId = (await composerResponse.json()).media_id as number;
    expect(await projectsOf(page, composerMediaId)).toEqual([q.id]);
  });

  test('Send to Tool and run inside P puts the output in P only', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const source = await generateMedia(page, `world send source ${stamp()}`, p.id);

    await page.goto(`/projects/${p.id}/assets`);
    await expectContext(page, p.name);
    await openTileMenu(page, source);
    await page.getByRole('button', { name: 'Send to Tool', exact: true }).filter({ visible: true }).first().hover();
    const submenu = page.locator('div.fixed.z-submenu').filter({ visible: true }).filter({ hasText: /Image/ }).last();
    await expect(submenu).toBeVisible();
    const toolRow = submenu.getByRole('button', { name: /Test Image to Image/ }).first();
    if (!(await toolRow.isVisible().catch(() => false))) {
      await submenu.getByRole('button', { name: /Image to Image|Edit/i }).first().click();
    }
    await submenu.getByRole('button', { name: /Test Image to Image/ }).first().click();
    await expect(page).toHaveURL(new RegExp(`/tools/${TEST_I2I_TOOL_ID}.*project_id=${p.id}`));
    await expect(page.locator('[data-drop-zone="media-picker-image"] img').first()).toBeVisible({ timeout: 30000 });

    const prompt = `world send output ${stamp()}`;
    await submitGeneration(page, prompt);
    const output = await waitFor(async () => {
      const items = await listMedia(page, { page: 1, page_size: 20, prompt_query: prompt, tool_id: TEST_I2I_TOOL_ID });
      return items[0] ?? null;
    }, 30000, 'image-to-image output');
    expect(await projectsOf(page, output.id)).toEqual([p.id]);
    expect(await inProject(page, q.id, output.id)).toBe(false);
  });

  test('the Projects submenu shows membership with checkmarks and toggles it', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const media = await generateMedia(page, `world submenu ${stamp()}`, p.id);

    await page.goto(`/projects/${p.id}/assets`);
    await openTileMenu(page, media);
    await page.getByRole('button', { name: 'Projects', exact: true }).filter({ visible: true }).hover();
    const rowP = page.getByRole('menuitemcheckbox', { name: new RegExp(p.name) });
    const rowQ = page.getByRole('menuitemcheckbox', { name: new RegExp(q.name) });
    await expect(rowP).toHaveAttribute('aria-checked', 'true');
    await expect(rowQ).toHaveAttribute('aria-checked', 'false');

    await rowQ.click();
    await expect(rowQ).toHaveAttribute('aria-checked', 'true');
    await expect.poll(() => projectsOf(page, media.id).then(ids => ids.sort())).toEqual([p.id, q.id].sort());

    await rowQ.click();
    await expect(rowQ).toHaveAttribute('aria-checked', 'false');
    await expect.poll(() => projectsOf(page, media.id)).toEqual([p.id]);
  });

  test('Remove from Project takes the tile off the project grid at once', async ({ page }) => {
    const { p } = await twoProjects(page);
    const media = await generateMedia(page, `world remove ${stamp()}`, p.id);

    await page.goto(`/projects/${p.id}/assets`);
    await openTileMenu(page, media);
    await page.getByRole('button', { name: 'Remove from Project', exact: true }).filter({ visible: true }).click();
    await expect(tile(page, media)).toHaveCount(0, { timeout: 5000 });
    await expect.poll(() => projectsOf(page, media.id)).toEqual([]);
  });

  test('dropping an asset on a project row adds it to that project, from the top level and from inside a project', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const loose = await generateMedia(page, `world drop loose ${stamp()}`);
    const fromP = await generateMedia(page, `world drop from P ${stamp()}`, p.id);

    // Top level: the sidebar's recent project rows take drops.
    // Generating in P left the window working in P.
    await page.goto('/home');
    await expectContext(page, p.name);
    await chooseContext(page, 'Everything');
    const row = sidebar(page).getByRole('region', { name: 'Projects' }).getByRole('button', { name: q.name, exact: true });
    await row.evaluate(dropMedia(loose.id), loose.id);
    await expect.poll(() => projectsOf(page, loose.id)).toEqual([q.id]);

    // Inside P: the project picker's rows take drops too.
    await page.goto(`/projects/${p.id}/assets`);
    await expectContext(page, p.name);
    await sidebar(page).getByRole('button', { name: 'Working context', exact: true }).click();
    const picker = page.getByRole('dialog', { name: 'Choose a project' });
    const pickerRow = picker.locator('div.group').filter({ has: page.getByRole('button', { name: q.name, exact: true }) });
    await pickerRow.evaluate(dropMedia(fromP.id), fromP.id);
    await expect.poll(() => projectsOf(page, fromP.id).then(ids => ids.sort())).toEqual([p.id, q.id].sort());
    await expectContext(page, p.name);
  });

  test('breaking apart a set that belongs to P puts its members in P', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const a = await generateMedia(page, `world set member a ${stamp()}`);
    const b = await generateMedia(page, `world set member b ${stamp()}`);
    const set = await apiJSON<{ media_id: number; asset_id: number }>(page, '/api/media/sets', {
      method: 'POST',
      data: { media_ids: [a.id, b.id], title: `World set ${stamp()}`, project_id: p.id },
    } as any);

    // Linking existing assets into a set doesn't file them; breaking it apart does.
    expect(await inProject(page, p.id, a.id)).toBe(false);
    expect(await projectsOf(page, set.media_id)).toEqual([p.id]);

    await page.goto(`/projects/${p.id}/assets`);
    await openTileMenu(page, { id: set.media_id, asset_id: set.asset_id });
    await page.getByRole('button', { name: /^Save members as assets/ }).filter({ visible: true }).click();
    await page.getByRole('button', { name: 'Save as assets', exact: true }).click();
    await expect(page.getByText(/container moved to Trash/)).toBeVisible({ timeout: 10000 });

    for (const member of [a, b]) {
      await expect.poll(() => inProject(page, p.id, member.id)).toBe(true);
      expect(await inProject(page, q.id, member.id)).toBe(false);
    }
  });

  test('cloning a chat in P makes the clone in P and stays in P', async ({ page }) => {
    const { p } = await twoProjects(page);
    const chat = await createChat(page, `World clone ${stamp()}`, p.id);

    await page.goto(`/chat/${chat.id}`);
    await expectContext(page, p.name);
    await page.getByTitle('More options').first().click();
    await page.getByRole('button', { name: 'Clone chat' }).click();
    await expect(page).not.toHaveURL(new RegExp(`/chat/${chat.id}(?:$|[?#])`), { timeout: 10000 });
    await expect(page).toHaveURL(/\/chat\/\d+/);
    const cloneId = Number(new URL(page.url()).pathname.split('/').pop());
    expect(cloneId).not.toBe(chat.id);
    expect((await getChat(page, cloneId)).project_id).toBe(p.id);
    await expectContext(page, p.name);
  });

  test('top-level Chats, Boards and Flows list no project items', async ({ page }) => {
    const { p } = await twoProjects(page);
    const tag = stamp();
    await createChat(page, `World loose chat ${tag}`);
    await createChat(page, `World P chat ${tag}`, p.id);
    await createBoard(page, `World loose board ${tag}`);
    await createBoard(page, `World P board ${tag}`, p.id);
    await apiJSON(page, '/api/flows', { method: 'POST', data: { name: `World loose flow ${tag}` } } as any);
    await apiJSON(page, '/api/flows', { method: 'POST', data: { name: `World P flow ${tag}`, project_id: p.id } } as any);

    for (const [route, noun] of [['/chats', 'chat'], ['/boards', 'board'], ['/flows', 'flow']] as const) {
      await page.goto(route);
      await expectContext(page, 'Everything');
      await expect(page.getByText(`World loose ${noun} ${tag}`).first()).toBeVisible({ timeout: 15000 });
      await expect(page.getByText(`World P ${noun} ${tag}`)).toHaveCount(0);
    }

    // Inside P the same pages show only P's items.
    await page.goto(`/projects/${p.id}/chats`);
    await expect(page.getByText(`World P chat ${tag}`).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(`World loose chat ${tag}`)).toHaveCount(0);
  });

  test('top-level Assets hides project assets until Include project assets is on', async ({ page }) => {
    const { p } = await twoProjects(page);
    const tag = stamp();
    const loose = await generateMedia(page, `world assets loose ${tag}`);
    const scoped = await generateMedia(page, `world assets scoped ${tag}`, p.id);

    await page.goto('/browse');
    await expectContext(page, p.name);
    await chooseContext(page, 'Everything');
    await expect(page).toHaveURL(/\/browse/);
    await expect(tile(page, loose)).toBeVisible({ timeout: 30000 });
    await expect(tile(page, scoped)).toHaveCount(0);

    await page.getByRole('button', { name: 'Filters', exact: true }).click();
    const include = page.getByTestId('include-project-assets');
    await expect(include).toHaveAttribute('aria-checked', 'false');
    await include.click();
    await expect(include).toHaveAttribute('aria-checked', 'true');
    await expect(tile(page, scoped)).toBeVisible({ timeout: 30000 });
    await expect(tile(page, loose)).toBeVisible();

    // The same view as a link.
    await page.goto('/browse?include_projects=1');
    await expect(tile(page, scoped)).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('include-project-assets')).toHaveCount(0); // panel closed
  });

  test('search inside P offers the matches outside it and opening one switches project', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const word = `zebrafish${Date.now().toString(36)}`;
    await createChat(page, `${word} in P`, p.id);
    const qChat = await createChat(page, `${word} in Q`, q.id);

    await page.goto(`/projects/${p.id}/overview`);
    await expectContext(page, p.name);
    const search = page.getByPlaceholder('Search or jump to…');
    await search.click();
    await search.fill(word);
    const dropdown = page.locator('.global-search-box').locator('div.absolute').filter({ hasText: word }).first();
    await expect(dropdown.getByText(`${word} in P`)).toBeVisible({ timeout: 15000 });
    await expect(dropdown.getByText(`${word} in Q`)).toHaveCount(0);
    const outside = dropdown.getByText(`1 more result outside ${p.name}`);
    await expect(outside).toBeVisible({ timeout: 15000 });

    await outside.click();
    await expect(dropdown.getByText(`${word} in Q`)).toBeVisible({ timeout: 15000 });
    await dropdown.getByText(`${word} in Q`).click();
    await expect(page).toHaveURL(new RegExp(`/chat/${qChat.id}`));
    await expectContext(page, q.name);
  });

  test('an asset deep link from Q to a P-only asset switches to P', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    const media = await generateMedia(page, `world deep link ${stamp()}`, p.id);
    const assetId = media.asset_id ?? media.id;

    await page.goto(`/projects/${q.id}/assets`);
    await expectContext(page, q.name);
    await page.goto(`/edit-image/${assetId}`);
    await expect(page).toHaveURL(new RegExp(`/edit-image/${assetId}`));
    await expectContext(page, p.name);

    // An asset that Q also holds keeps Q.
    await addMediaToProject(page, q.id, [media.id]);
    await page.goto(`/projects/${q.id}/assets`);
    await expectContext(page, q.name);
    await page.goto(`/lineage/${assetId}`);
    await expectContext(page, q.name);
  });

  test('deleting P closes its tabs and lands on the top-level Home', async ({ page }) => {
    const { p, q } = await twoProjects(page);
    await openToolById(page, TEST_I2I_TOOL_ID, p.id);
    await expectContext(page, p.name);
    const tabRow = sidebar(page).getByRole('button', { name: /Test Image to Image/ }).first();
    await expect(tabRow).toBeVisible();

    await sidebar(page).getByRole('button', { name: 'Working context', exact: true }).click();
    const picker = page.getByRole('dialog', { name: 'Choose a project' });
    await picker.getByRole('button', { name: `Manage ${p.name}` }).click();
    await picker.getByRole('button', { name: 'Delete project' }).click();
    await page.getByRole('button', { name: 'Delete', exact: true }).click();

    await expect(page).toHaveURL(/\/home/, { timeout: 10000 });
    await expectContext(page, 'Everything');
    await expect(sidebar(page).getByRole('region', { name: 'Projects' }).getByRole('button', { name: p.name, exact: true })).toHaveCount(0);
    await chooseContext(page, q.name);
    await chooseContext(page, 'Everything');
    const tabs = await page.evaluate(() => Object.entries(localStorage)
      .filter(([key]) => key.endsWith('workspace_tabs'))
      .flatMap(([, value]) => JSON.parse(value) as Array<{ projectId?: number | null; contextProjectIds?: number[] }>));
    expect(tabs.filter(t => t.projectId === p.id || t.contextProjectIds?.includes(p.id))).toEqual([]);
  });

  test('the Home composer sends its first message exactly once', async ({ page }) => {
    await page.route('**/api/models/available*', route => route.fulfill({ json: {
      models: [{ slug: 'local', name: 'Test model', available: true, selectable: true, source: 'endpoint' }], global_default: 'local', llm_configured: true,
    } }));
    const { p } = await twoProjects(page);
    for (const scope of ['Everything', p.name]) {
      await page.goto('/home');
      await waitForShell(page);
      await chooseContext(page, scope);
      if (scope !== 'Everything') await sidebar(page).getByRole('button', { name: 'Home', exact: true }).click();
      const posts: string[] = [];
      const onRequest = (req: any) => {
        if (req.method() === 'POST' && /\/api\/chats\/\d+\/items$/.test(new URL(req.url()).pathname)) posts.push(req.url());
      };
      page.on('request', onRequest);
      const message = `world once ${stamp()}`;
      const composer = page.getByPlaceholder('Type a message...');
      await composer.fill(message);
      await composer.press('Enter');
      await expect(page).toHaveURL(/\/chat\/\d+/, { timeout: 10000 });
      const chatId = Number(new URL(page.url()).pathname.split('/').pop());
      await expect.poll(() => posts.length, { timeout: 10000 }).toBeGreaterThanOrEqual(1);
      await page.waitForTimeout(2000);
      page.off('request', onRequest);
      expect(posts).toHaveLength(1);
      const items = await apiJSON<{ items: Array<{ item_type: string; message_text?: string | null }> }>(page, `/api/chats/${chatId}/items?visible_limit=500`);
      expect(items.items.filter(i => i.message_text === message)).toHaveLength(1);
    }
  });

  test('a fresh install shows only the Projects header with a +', async ({ page }) => {
    await page.route('**/api/projects', async route => {
      if (route.request().method() === 'GET') await route.fulfill({ json: [] });
      else await route.continue();
    });
    await page.goto('/home');
    await waitForShell(page);
    const projects = sidebar(page).getByRole('region', { name: 'Projects' });
    const plus = projects.getByRole('button', { name: 'New project', exact: true });
    await expect(plus).toBeVisible();
    await expect(plus).toHaveCSS('opacity', '1');
    // Nothing but the header: no rows, no help sentence, no All projects.
    await expect(projects).toHaveText(/^\s*Projects\s*$/);
    await expect(projects.getByText('Keep the assets, chats and boards')).toHaveCount(0);
    await expect(projects.getByRole('button', { name: /^All projects/ })).toHaveCount(0);
  });
});
