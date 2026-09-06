import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

test('MCP setup exposes usable connection details without developer tooling', async ({ page, context }, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'MCP', exact: true }).click();
  const enabled = page.getByRole('switch', { name: 'Allow assistants to connect to this profile' });
  await expect(enabled).not.toBeChecked();
  await enabled.click({ force: true });
  await expect(enabled).toBeChecked();
  await expect(page.getByText('No assistants connected yet')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('mcp-settings.png') });

  await page.getByRole('button', { name: 'New connection', exact: true }).click();
  const name = page.getByRole('textbox', { name: 'Connection name' });
  await name.fill('Claude Desktop');
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/mcp/clients') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create & show key', exact: true }).click();
  const { connection } = await (await responsePromise).json();
  expect(connection.path).toBe(`/mcp/profiles/${connection.profile_id}`);
  expect(connection.endpoint).toContain(connection.path);
  await expect(page.getByText('Claude Desktop is ready to connect')).toBeVisible();
  await page.getByRole('button', { name: 'Copy URL', exact: true }).click();
  // In the browser lane this is the backend's own address; inside the Electron
  // shell it is the proxy origin. Either way it is what a person would paste.
  const serverUrl = await page.evaluate(() => navigator.clipboard.readText());
  expect(serverUrl).toMatch(new RegExp(`^http://127\\.0\\.0\\.1:\\d+${connection.path}$`));
  await page.getByRole('button', { name: 'Copy key', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(connection.credential);
  await expect(page.getByText(connection.credential, { exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: 'Reveal', exact: true }).click();
  await expect(page.getByText(connection.credential, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Hide', exact: true }).click();
  await expect(page.getByText(/Stimma CLI|connection file|Lock external access|isn’t supported|Streamable HTTP|PIN/)).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('mcp-created.png') });
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByText(connection.credential, { exact: true })).toHaveCount(0);

  // The copied URL and credential must authenticate a real MCP session.
  const mcp = await page.request.post(serverUrl, {
    headers: { Authorization: `Bearer ${connection.credential}`, Accept: 'application/json, text/event-stream' },
    data: { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'acceptance', version: '1' } } },
  });
  expect(mcp.ok()).toBeTruthy();
  expect(await mcp.text()).toContain('serverInfo');

  // The row shows the name plus created / last-used, and supports rename.
  const row = page.getByTestId('mcp-connection-row').filter({ hasText: 'Claude Desktop' });
  await expect(row).toBeVisible();
  await expect(row).not.toContainText('Never', { timeout: 15000 });
  await row.getByRole('button', { name: 'Options for Claude Desktop' }).click();
  await page.getByRole('menuitem', { name: 'Rename…' }).click();
  await page.getByRole('textbox', { name: 'Connection name' }).fill('Claude on laptop');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByTestId('mcp-connection-row').filter({ hasText: 'Claude on laptop' })).toBeVisible();

  await page.getByRole('button', { name: 'Options for Claude on laptop' }).click();
  await page.getByRole('menuitem', { name: 'Remove connection' }).click();
  await expect(page.getByText('No assistants connected yet')).toBeVisible();
  const revoked = await page.request.post(serverUrl, {
    headers: { Authorization: `Bearer ${connection.credential}`, Accept: 'application/json, text/event-stream' },
    data: { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} },
  });
  expect(revoked.ok()).toBeFalsy();
  await enabled.click({ force: true });
  await expect(enabled).not.toBeChecked();
});
