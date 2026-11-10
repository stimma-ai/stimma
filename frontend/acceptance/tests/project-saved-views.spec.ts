import { expect, test } from '../helpers/testbed';
import { apiJSON, chooseContext, createProject, expectContext, waitForShell } from '../helpers/app';

const sidebar = (page: any) => page.locator('.navigation-sidebar');
const choose = chooseContext;

test('saved views are created, restored and listed within their owning context', async ({ page }) => {
  await page.goto('/browse?library=1');
  await waitForShell(page);
  const project = await createProject(page, 'View ownership');
  const other = await createProject(page, 'Other view ownership');
  const global = await apiJSON<any>(page, '/api/saved-views', { method: 'POST', data: {
    name: 'Review picks', filters: {}, sort_by: 'created_desc',
  } } as any);
  await choose(page, project.name);
  await page.getByRole('button', { name: 'Newest first', exact: true }).click();
  await page.getByRole('option', { name: 'Oldest first', exact: true }).click();
  await page.getByTitle('Filter options').click();
  await page.getByRole('button', { name: 'Save view', exact: true }).click();
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
  // Inside Assets every saved view shows under it.
  await sidebar(page).getByRole('button', { name: 'Review picks', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/saved-view/${global.id}`));
  const scopedRequest = page.waitForRequest(r => new URL(r.url()).pathname === '/api/assets/browse' && new URL(r.url()).searchParams.get('project_id') === String(project.id));
  await page.goto(`/saved-view/${saved.id}`);
  await scopedRequest;
  await expectContext(page, project.name);
  await page.reload();
  await expectContext(page, project.name);
  await expect(page.getByRole('button', { name: 'Oldest first', exact: true })).toBeVisible();
});

test('saved views show inside Assets, and pinned ones everywhere', async ({ page }) => {
  await page.goto('/browse?library=1');
  await waitForShell(page);
  await apiJSON<any>(page, '/api/saved-views', { method: 'POST', data: { name: 'Keepers', filters: {}, sort_by: 'created_desc' } } as any);
  const row = sidebar(page).getByRole('button', { name: 'Keepers', exact: true });
  await expect(row).toBeVisible();
  await sidebar(page).getByRole('button', { name: 'Home', exact: true }).click();
  await expect(row).toHaveCount(0);
  await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
  await expect(row).toBeVisible();
  const pinned = page.waitForResponse(r => /\/api\/saved-views\/\d+$/.test(r.url()) && r.request().method() === 'PUT');
  await row.hover();
  await sidebar(page).getByTestId('sidebar-saved-view').filter({ hasText: 'Keepers' }).getByRole('button', { name: 'Pin', exact: true }).click();
  expect((await (await pinned).json()).pinned).toBe(true);
  await sidebar(page).getByRole('button', { name: 'Home', exact: true }).click();
  await expect(row).toBeVisible();
  await sidebar(page).getByRole('button', { name: 'Assets', exact: true }).click();
  await page.reload();
  await waitForShell(page);
  const reloaded = await apiJSON<any[]>(page, '/api/saved-views');
  expect(reloaded.find(v => v.name === 'Keepers')?.pinned).toBe(true);
  await row.click({ button: 'right' });
  await page.getByText('Unpin', { exact: true }).click();
  await expect(row).toBeVisible();
  await sidebar(page).getByRole('button', { name: 'Home', exact: true }).click();
  await expect(row).toHaveCount(0);
});
