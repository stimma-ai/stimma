import { expect, test } from '../helpers/testbed';
import { apiJSON, createProject, waitForShell } from '../helpers/app';

const label = 'Enable Flows';

test('Flows opt-in hides all entry points and preserves existing flows', async ({ page }) => {
  await page.goto('/browse');
  await waitForShell(page);
  const sidebar = page.locator('.navigation-sidebar');
  const flowLink = sidebar.getByRole('button', { name: 'Flows', exact: true });
  await expect(flowLink).toHaveCount(0);
  const flow = await apiJSON<{ id: number }>(page, '/api/flows', { method: 'POST', data: { name: 'Experimental flow' } } as any);
  const chat = await apiJSON<{ id: number }>(page, '/api/chats', { method: 'POST', data: { flow_id: flow.id } } as any);
  const otherChat = await apiJSON<{ id: number }>(page, '/api/chats', { method: 'POST', data: { flow_id: flow.id } } as any);
  await apiJSON(page, `/api/chats/${chat.id}/items`, { method: 'POST', data: { item_type: 'assistant_message', message_text: 'Requested flow conversation' } } as any);
  await apiJSON(page, `/api/chats/${otherChat.id}/items`, { method: 'POST', data: { item_type: 'assistant_message', message_text: 'Other flow conversation' } } as any);
  const project = await createProject(page, 'Experimental project');
  // Creating flows later never overrides the migration-time decision.
  for (const path of ['/flows', `/flows/${flow.id}`, `/projects/${project.id}/flows`, `/chat/${chat.id}`]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/(home|projects\/\d+\/overview)$/);
  }
  await page.goto('/browse');
  await waitForShell(page);
  await sidebar.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Preferences', exact: true }).click();
  const toggle = page.getByRole('switch', { name: label, exact: true });
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect(page.getByText(/Flows are an experiment and may change or be removed/)).toBeVisible();
  await page.screenshot({ path: '/tmp/stimma-flows-disabled.png' });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Close', exact: true }).last().click();
  await expect(flowLink).toBeVisible();
  await page.goto(`/flows/${flow.id}`);
  await page.getByTitle('Hide chat panel', { exact: true }).click();
  await expect(page.getByTitle('Show chat panel', { exact: true })).toBeVisible();
  // Direct flow-chat links reopen a closed panel on the requested session.
  await page.goto(`/chat/${chat.id}`);
  await expect(page).toHaveURL(new RegExp(`/flows/${flow.id}\\?chat=${chat.id}$`));
  await expect(page.getByText('Requested flow conversation', { exact: true })).toBeVisible();
  await expect(page.getByText('Other flow conversation', { exact: true })).toHaveCount(0);
  await page.getByTitle('Hide chat panel', { exact: true }).click();
  // Query-only navigation also reopens a closed panel in an already-mounted flow.
  await page.evaluate(id => window.history.pushState({}, '', `/chat/${id}`), otherChat.id);
  await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate')));
  await expect(page.getByText('Other flow conversation', { exact: true })).toBeVisible();
  await expect(page.getByText('Requested flow conversation', { exact: true })).toHaveCount(0);
  await sidebar.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Preferences', exact: true }).click();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect(page).toHaveURL(/\/(home|projects\/\d+\/overview)$/);
  await page.getByRole('button', { name: 'Close', exact: true }).last().click();
  await expect(flowLink).toHaveCount(0);
  await expect(sidebar.getByText('Experimental flow', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(flowLink).toHaveCount(0);
  // Search and Home cannot resurface saved flows when the feature is off.
  await page.goto('/search?q=Experimental');
  await expect(page.getByRole('heading', { name: 'Flows', exact: true })).toHaveCount(0);
  await expect(page.getByText('Experimental flow', { exact: true })).toHaveCount(0);
  expect((await apiJSON<any>(page, `/api/flows/${flow.id}`)).id).toBe(flow.id);
});
