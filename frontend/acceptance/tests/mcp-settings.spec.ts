import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';
import { createServer } from 'node:net';

test('Direct MCP setup works without the desktop relay and can be disabled', async ({ page, context }, testInfo) => {
  const reservation = createServer();
  await new Promise<void>(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = (reservation.address() as { port: number }).port;
  await new Promise<void>((resolve, reject) => reservation.close(error => error ? reject(error) : resolve()));
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'MCP EXPERIMENTAL', exact: true }).click();
  const profileEnabled = page.getByRole('switch', { name: /^Enable MCP Server(?: for this profile)?$/ });
  await expect(profileEnabled).toBeEnabled();
  if (!await profileEnabled.isChecked()) await profileEnabled.click({ force: true });
  const direct = page.getByTestId('mcp-direct-settings');
  await expect(direct.getByRole('switch')).toBeEnabled();
  await direct.getByRole('switch').check({ force: true });
  await direct.getByRole('spinbutton', { name: 'Port' }).fill(String(port));
  await direct.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(page.getByTestId('mcp-direct-status')).toHaveText('Listening');
  await expect(page.getByTestId('mcp-direct-url')).toContainText(`http://127.0.0.1:${port}/mcp/profiles/`);
  await page.getByRole('button', { name: '+ New', exact: true }).click();
  await page.getByRole('textbox', { name: 'Connection name' }).fill('Headless agent');
  const created = page.waitForResponse(response => response.url().endsWith('/api/mcp/clients') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create & show key', exact: true }).click();
  const { connection } = await (await created).json();
  await expect(page.getByRole('radio', { name: 'Direct to server', exact: true })).toBeChecked();
  await page.getByRole('button', { name: 'Copy URL', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(connection.direct_endpoint);
  await page.getByRole('button', { name: 'Copy setup request', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(connection.direct_endpoint);
  await page.screenshot({ path: testInfo.outputPath('mcp-direct-setup.png') });
  const initialize = await page.request.post(connection.direct_endpoint, {
    headers: { Authorization: `Bearer ${connection.credential}`, Accept: 'application/json, text/event-stream' },
    data: { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'direct-acceptance', version: '1' } } },
  });
  expect(initialize.ok()).toBeTruthy();
  expect(await initialize.text()).toContain('serverInfo');
  const origin = new URL(connection.direct_endpoint).origin;
  expect((await page.request.get(`${origin}/api/settings`)).status()).toBe(404);
  await page.getByRole('radio', { name: 'Through this app', exact: true }).check();
  await page.getByRole('button', { name: 'Copy URL', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).not.toBe(connection.direct_endpoint);
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  // Draft edits survive the periodic refresh until Apply is pressed.
  await direct.getByRole('spinbutton', { name: 'Port' }).fill('19295');
  await page.waitForTimeout(10500);
  await expect(direct.getByRole('spinbutton', { name: 'Port' })).toHaveValue('19295');
  await direct.getByRole('switch').uncheck({ force: true });
  await direct.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(page.getByTestId('mcp-direct-status')).toHaveText('Off');
  await expect(page.getByTestId('mcp-direct-url')).toHaveCount(0);
  await page.getByRole('button', { name: 'Options for Headless agent' }).click();
  await page.getByRole('menuitem', { name: 'Remove connection' }).click();
  await expect(page.getByText('No assistants connected yet')).toBeVisible();
  await expect(profileEnabled).toBeEnabled();
  const disabled = page.waitForResponse(response => response.url().endsWith('/api/mcp/settings') && response.request().method() === 'PUT');
  await profileEnabled.click({ force: true });
  expect((await disabled).ok()).toBeTruthy();
  await expect(profileEnabled).not.toBeChecked();
  await expect(profileEnabled).toBeEnabled();
});

test('MCP setup exposes usable connection details without developer tooling', async ({ page, context }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1100 });
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'MCP EXPERIMENTAL', exact: true }).click();
  const enabled = page.getByRole('switch', { name: /^Enable MCP Server(?: for this profile)?$/ });
  await expect(enabled).toBeEnabled();
  await expect(enabled).not.toBeChecked();
  await enabled.click({ force: true });
  await expect(enabled).toBeChecked();
  await expect(page.getByText('No assistants connected yet')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('mcp-settings.png') });

  await page.getByRole('button', { name: '+ New', exact: true }).click();
  const name = page.getByRole('textbox', { name: 'Connection name' });
  await name.fill('Claude Code');
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/mcp/clients') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create & show key', exact: true }).click();
  const { connection } = await (await responsePromise).json();
  expect(connection.path).toBe(`/mcp/profiles/${connection.profile_id}`);
  expect(connection.endpoint).toContain(connection.path);
  await expect(page.getByText('Claude Code is ready to connect')).toBeVisible();
  await page.getByRole('button', { name: 'Copy URL', exact: true }).click();
  // In the browser lane this is the backend's own address; inside the Electron
  // shell it is the proxy origin. Either way it is what a person would paste.
  const serverUrl = await page.evaluate(() => navigator.clipboard.readText());
  expect(serverUrl).toMatch(new RegExp(`^http://127\\.0\\.0\\.1:\\d+${connection.path}$`));
  await page.getByRole('button', { name: 'Copy setup request', exact: true }).click();
  const setupRequest = await page.evaluate(() => navigator.clipboard.readText());
  expect(setupRequest).toContain(`Server URL: ${serverUrl}`);
  expect(setupRequest).toContain(`Authorization header: Bearer ${connection.credential}`);
  expect(setupRequest).toContain('Transport: Streamable HTTP');
  await page.getByRole('button', { name: 'Copy key', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(connection.credential);
  await expect(page.getByText(connection.credential, { exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: 'Reveal', exact: true }).click();
  await expect(page.getByText(connection.credential, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Hide', exact: true }).click();
  await expect(page.getByText(/Stimma CLI|connection file|Lock external access|isn’t supported|Streamable HTTP|PIN/)).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('mcp-created.png') });
  await expect(page.getByRole('button', { name: 'Copy key', exact: true })).toBeVisible();
  const settingsModal = page.locator('[data-modal-layer] > [tabindex="-1"]').filter({
    has: page.getByRole('heading', { name: 'Settings', exact: true }),
  });
  const bounds = await settingsModal.boundingBox();
  if (!bounds) throw new Error('Settings modal is not visible');
  await page.screenshot({
    path: testInfo.outputPath('mcp-setup-request.png'),
    clip: { x: bounds.x - 20, y: bounds.y - 20, width: bounds.width + 40, height: bounds.height + 40 },
  });
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
  const row = page.getByTestId('mcp-connection-row').filter({ hasText: 'Claude Code' });
  await expect(row).toBeVisible();
  await expect(row).not.toContainText('Never', { timeout: 15000 });
  await row.getByRole('button', { name: 'Options for Claude Code' }).click();
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
