import { expect, test } from '../helpers/testbed';
import { apiJSON, createProject, waitForShell } from '../helpers/app';

const sidebar = (page: any) => page.locator('.navigation-sidebar');
async function choose(page: any, name: string) {
  await sidebar(page).getByRole('button', { name: 'Working context', exact: true }).click();
  await page.getByRole('dialog', { name: 'Choose working context' }).getByRole('button', { name, exact: true }).click();
}

test('saved views are created, restored and listed within their owning context', async ({ page }) => {
  await page.goto('/browse?library=1');
  await waitForShell(page);
  const project = await createProject(page, 'View ownership');
  const other = await createProject(page, 'Other view ownership');
  const global = await apiJSON<any>(page, '/api/saved-views', { method: 'POST', data: {
    name: 'Review picks', filters: {}, sort_by: 'created_desc',
  } } as any);
  await choose(page, project.name);
  await page.getByRole('button', { name: 'Newest First', exact: true }).click();
  await page.getByRole('option', { name: 'Oldest First', exact: true }).click();
  await page.getByTitle('Filter options').click();
  await page.getByRole('button', { name: 'Save View', exact: true }).click();
  await page.getByPlaceholder('View name').fill('Review picks');
  const created = page.waitForResponse(r => r.url().endsWith('/api/saved-views') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const saved = await (await created).json();
  expect(saved.project_id).toBe(project.id);
  await expect(page).toHaveURL(new RegExp(`/saved-view/${saved.id}`));
  await expect(sidebar(page).getByRole('button', { name: 'Review picks', exact: true })).toHaveCount(1);
  await choose(page, other.name);
  await expect(sidebar(page).getByRole('button', { name: 'Review picks', exact: true })).toHaveCount(0);
  await choose(page, 'Everything');
  await sidebar(page).getByRole('button', { name: 'Review picks', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/saved-view/${global.id}`));
  const scopedRequest = page.waitForRequest(r => new URL(r.url()).pathname === '/api/assets/browse' && new URL(r.url()).searchParams.get('project_id') === String(project.id));
  await page.goto(`/saved-view/${saved.id}`);
  await scopedRequest;
  await expect(sidebar(page).getByRole('button', { name: 'Working context', exact: true })).toHaveText(project.name);
  await page.reload();
  await expect(sidebar(page).getByRole('button', { name: 'Working context', exact: true })).toHaveText(project.name);
  await expect(page.getByRole('button', { name: 'Oldest First', exact: true })).toBeVisible();
});
