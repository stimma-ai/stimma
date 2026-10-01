import { expect, test } from '../helpers/testbed';
import { apiJSON, createProject, generateMedia, listMedia, openTool, openToolById, promptInput, submitGeneration, TEST_I2I_TOOL_ID, waitFor, waitForShell } from '../helpers/app';

const promptText = (page: any) => promptInput(page).evaluate(el => [...el.querySelectorAll('.cm-line')].map(line => {
  const clone = line.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.cm-placeholder').forEach(node => node.remove());
  return clone.textContent;
}).join('\n'));
const sidebar = (page: any) => page.locator('.navigation-sidebar');
async function choose(page: any, name: string) {
  await sidebar(page).getByRole('button', { name: 'Working context', exact: true }).click();
  await page.getByRole('dialog', { name: 'Choose working context' }).getByRole('button', { name, exact: true }).click();
}

test.describe('working context', () => {
  test('no projects keeps a quiet picker, and legacy projects links open it', async ({ page }) => {
    await page.route('**/api/projects', async route => {
      if (route.request().method() === 'GET') await route.fulfill({ json: [] });
      else await route.continue();
    });
    await page.goto('/browse');
    await waitForShell(page);
    await expect(sidebar(page).getByRole('button', { name: 'Working context' })).toHaveText('Everything');
    await expect(sidebar(page).getByRole('button', { name: 'Projects', exact: true })).toHaveCount(0);
    await sidebar(page).getByRole('button', { name: 'Working context' }).click();
    const picker = page.getByRole('dialog', { name: 'Choose working context' });
    await expect(picker.getByRole('button', { name: 'New project' })).toBeVisible();
    await expect(picker.getByRole('textbox')).toHaveCount(0);
    await expect(picker.getByText('Recent projects')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(picker).toBeHidden();
    await expect(sidebar(page).getByRole('button', { name: 'Working context' })).toBeFocused();
    await page.goto('/projects');
    await expect(picker).toBeVisible();
    await expect(page).toHaveURL(/\/home/);
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
    await sidebar(page).getByRole('button', { name: 'Working context' }).click();
    const picker = page.getByRole('dialog', { name: 'Choose working context' });
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
    await expect(page).toHaveURL(new RegExp(`project_id=${project.id}`));
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
    await choose(page, project.name);
    await expect.poll(() => promptText(page)).toBe(prompt);
    expect(new URL(page.url()).searchParams.get('instance')).toBe(scopedInstance);
    await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/assets`));
  });

  test('an Everything image dropped on a project tool session produces project output', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);
    const source = await generateMedia(page, `context borrowed input ${Date.now()}`);
    const project = await createProject(page, 'Context handoff');
    await apiJSON(page, '/api/tools/pin', { method: 'POST', data: { full_tool_id: TEST_I2I_TOOL_ID } } as any);
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
