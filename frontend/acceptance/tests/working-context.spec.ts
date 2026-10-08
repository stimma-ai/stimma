import { expect, test } from '../helpers/testbed';
import { apiJSON, chooseContext, createProject, expectContext, generateMedia, listMedia, openTool, openToolById, promptInput, submitGeneration, TEST_I2I_TOOL_ID, waitFor, waitForShell } from '../helpers/app';

const promptText = (page: any) => promptInput(page).evaluate(el => [...el.querySelectorAll('.cm-line')].map(line => {
  const clone = line.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.cm-placeholder').forEach(node => node.remove());
  return clone.textContent;
}).join('\n'));
const sidebar = (page: any) => page.locator('.navigation-sidebar');
const choose = chooseContext;

test.describe('working context', () => {
  test('no projects shows the Projects header with a + only, and legacy projects links open the picker', async ({ page }) => {
    await page.route('**/api/projects', async route => {
      if (route.request().method() === 'GET') await route.fulfill({ json: [] });
      else await route.continue();
    });
    await page.goto('/browse');
    await waitForShell(page);
    await expectContext(page, 'Everything');
    const projects = sidebar(page).getByRole('region', { name: 'Projects' });
    await expect(projects.getByRole('button', { name: 'New project', exact: true })).toBeVisible();
    // The hint lives in the + tooltip now, not as a sentence in the sidebar.
    await expect(projects.getByText('Keep the assets, chats and boards')).toHaveCount(0);
    await expect(projects.getByRole('button', { name: 'New project', exact: true })).toHaveAttribute('title', /keep the assets, chats and boards/);
    await page.goto('/projects');
    const picker = page.getByRole('dialog', { name: 'Choose a project' });
    await expect(picker).toBeVisible();
    await expect(picker.getByRole('button', { name: 'New project' })).toBeVisible();
    await expect(picker.getByRole('textbox')).toHaveCount(0);
    await expect(page).toHaveURL(/\/home/);
    await page.keyboard.press('Escape');
    await expect(picker).toBeHidden();
  });

  test('sidebar creates a project inline and enters it', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const projects = sidebar(page).getByRole('region', { name: 'Projects' });
    await projects.hover();
    await projects.getByRole('button', { name: 'New project', exact: true }).first().click();
    await projects.getByRole('textbox', { name: 'Project name' }).fill('Inline sidebar project');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/projects\/\d+\/overview/);
    await expectContext(page, 'Inline sidebar project');
    await chooseContext(page, 'Everything');
    await expect(projects.getByRole('button', { name: 'Inline sidebar project', exact: true })).toBeVisible();
  });

  test('picker keeps the browser section, searches every project and renames inline', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const project = await createProject(page, 'Context browser');
    for (let i = 0; i < 5; i++) await createProject(page, `Browser context ${i}`);
    await choose(page, project.name);
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/assets`));
    await sidebar(page).getByRole('button', { name: 'Boards', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/boards`));
    await choose(page, 'Everything');
    await expect(page).toHaveURL(/\/boards$/);
    await sidebar(page).getByRole('region', { name: 'Projects' }).getByRole('button', { name: /^All projects/ }).click();
    const picker = page.getByRole('dialog', { name: 'Choose a project' });
    await picker.getByRole('textbox', { name: 'Find a project' }).fill(project.name);
    await picker.getByRole('button', { name: `Manage ${project.name}` }).click();
    await picker.getByRole('textbox', { name: 'Project name' }).fill('Renamed context');
    await picker.getByRole('button', { name: 'Save name' }).click();
    await expect(picker.getByRole('button', { name: 'Renamed context', exact: true })).toHaveCount(0); // search still filters original text
    await picker.getByRole('textbox', { name: 'Find a project' }).fill('Renamed');
    await picker.getByRole('button', { name: 'Renamed context', exact: true }).click();
    await expect(sidebar(page).getByRole('button', { name: 'Working context' })).toHaveText('Renamed context');
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/boards`));
  });

  test('Home drafts and new chats belong to their selected context', async ({ page }) => {
    await page.route('**/api/models/available*', route => route.fulfill({ json: {
      models: [{ slug: 'local', name: 'Test model', available: true, selectable: true, source: 'endpoint' }], global_default: 'local', llm_configured: true,
    } }));
    await page.goto('/home');
    await waitForShell(page);
    const project = await createProject(page, 'Context home');
    await choose(page, project.name);
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/overview`));
    const composer = page.getByPlaceholder('Type a message...');
    await composer.fill('Project draft');
    await choose(page, 'Everything');
    await expect(composer).toHaveValue('');
    await composer.fill('Library draft');
    await choose(page, project.name);
    await expect(composer).toHaveValue('Project draft');
    await page.reload();
    await expect(composer).toHaveValue('Project draft');
    const created = page.waitForRequest(req => req.url().endsWith('/api/chats') && req.method() === 'POST');
    await composer.press('Enter');
    expect((await created).postDataJSON().project_id).toBe(project.id);
    await expect(page).toHaveURL(/\/chat\/\d+/);
    await sidebar(page).getByRole('button', { name: 'Home', exact: true }).click();
    await expect(composer).toHaveValue('');
    await choose(page, 'Everything');
    await expect(composer).toHaveValue('Library draft');
  });

  test('tool instances keep their drafts and submitted destination while switching context', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const project = await createProject(page, 'Context generation');
    await openTool(page);
    await promptInput(page).fill('Global tool draft');
    const globalInstance = new URL(page.url()).searchParams.get('instance');
    await choose(page, project.name);
    // The project has no instance of this tool yet: switching lands on its
    // overview instead of creating one.
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/overview`));
    await openTool(page, project.id);
    await expect.poll(() => promptText(page)).toBe('');
    const scopedInstance = new URL(page.url()).searchParams.get('instance');
    expect(scopedInstance).not.toBe(globalInstance);
    const prompt = `context retained output ${Date.now()}`;
    // Hold submission until after switching context. The resulting Asset must
    // still be attached to the initiating project's session.
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let submitted: any;
    await page.route('**/api/generate/submit', async route => {
      submitted = route.request().postDataJSON();
      await gate;
      await route.continue();
    });
    await submitGeneration(page, prompt);
    await expect.poll(() => submitted?.project_id).toBe(project.id);
    await choose(page, 'Everything');
    await expect.poll(() => promptText(page)).toBe('Global tool draft');
    await expect(sidebar(page).getByRole('button', { name: 'Test Text-to-Image Test Provider', exact: true })).toHaveClass(/bg-selection/);
    expect(new URL(page.url()).searchParams.get('instance')).toBe(globalInstance);
    release();
    await waitFor(async () => {
      const items = await listMedia(page, { prompt_query: prompt, project_id: project.id, page_size: 20 });
      return items.length ? items : null;
    }, 30000);
    // Back in the project, its own instance of the open tool is reused.
    await choose(page, project.name);
    await expect.poll(() => promptText(page)).toBe(prompt);
    expect(new URL(page.url()).searchParams.get('instance')).toBe(scopedInstance);
    await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/assets`));
  });

  test('sidebar pins retain backend persistence and stay in their project', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const project = await createProject(page, 'Context pins');
    await openToolById(page, TEST_I2I_TOOL_ID, project.id);
    const session = sidebar(page).getByRole('button', { name: /Test Image to Image/ }).first();
    await session.click({ button: 'right' });
    await page.getByRole('button', { name: 'Pin', exact: true }).click();
    await expect.poll(async () => (await apiJSON<any[]>(page, '/api/tools/pinned')).some(tool => tool.full_tool_id === TEST_I2I_TOOL_ID)).toBe(true);
    await page.reload();
    await waitForShell(page);
    await expect(sidebar(page).getByText('Pinned', { exact: true })).toBeVisible();
    await expect(session).toBeVisible();
    await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
    await choose(page, 'Everything');
    await expect(session).toHaveCount(0);
    await choose(page, project.name);
    await session.click({ button: 'right' });
    await page.getByRole('button', { name: 'Unpin', exact: true }).click();
    await expect.poll(async () => (await apiJSON<any[]>(page, '/api/tools/pinned')).some(tool => tool.full_tool_id === TEST_I2I_TOOL_ID)).toBe(false);
    await page.reload();
    await waitForShell(page);
    await expect(sidebar(page).getByText('Pinned', { exact: true })).toHaveCount(0);
    await expect(session).toBeVisible();
  });

  test('existing saved tool pins return as normal sidebar rows', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    await apiJSON(page, '/api/tools/pin', { method: 'POST', data: { full_tool_id: TEST_I2I_TOOL_ID } } as any);
    await page.reload();
    await waitForShell(page);
    await expect(sidebar(page).getByText('Pinned', { exact: true })).toBeVisible();
    const session = sidebar(page).getByRole('button', { name: /Test Image to Image/ }).first();
    await expect(session).toBeVisible();
    const bounds = await session.boundingBox();
    expect(bounds!.height).toBeLessThan(80);
    await expect(sidebar(page).getByText('Tool shortcuts', { exact: true })).toHaveCount(0);
    await apiJSON(page, `/api/tools/pin/${encodeURIComponent(TEST_I2I_TOOL_ID)}`, { method: 'DELETE' });
  });

  test('an Everything image dropped on a project tool session produces project output', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const source = await generateMedia(page, `context borrowed input ${Date.now()}`);
    const project = await createProject(page, 'Context handoff');
    await choose(page, project.name);
    await openToolById(page, TEST_I2I_TOOL_ID, project.id);
    await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
    await expect(sidebar(page).getByText('Tool shortcuts', { exact: true })).toHaveCount(0);
    const session = sidebar(page).getByRole('button', { name: /Test Image to Image/ }).first();
    await expect(session).toBeVisible();
    await session.evaluate((element, mediaId) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.setData('application/x-media-id', String(mediaId));
      element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
    }, source.id);
    await expect(page).toHaveURL(new RegExp(`project_id=${project.id}`));
    await expect(page.locator('[data-drop-zone="media-picker-image"]').getByText('1/3')).toBeVisible();
    const prompt = `context handoff output ${Date.now()}`;
    await submitGeneration(page, prompt);
    await waitFor(async () => {
      const items = await listMedia(page, { prompt_query: prompt, project_id: project.id, page_size: 20 });
      return items.length ? items : null;
    }, 30000);
    const projectItems = await listMedia(page, { project_id: project.id, page_size: 100 });
    expect(projectItems.some(item => item.id === source.id)).toBe(false);
  });
});
