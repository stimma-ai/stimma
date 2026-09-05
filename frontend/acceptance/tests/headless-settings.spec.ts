import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

test('server updates live on Stimma Server and start immediately from the top bar or server card', async ({ page }, testInfo) => {
  const actions: string[] = [];
  const server = {
    headless: true, version: '1.2.3', availableVersion: '1.2.4', status: 'ready', serverStartedAt: 1,
    bootstrapVersion: '1.0.0', latestBootstrapVersion: '1.0.0',
    bootstrapUpdateRequired: false, bootstrapUpdateAvailable: false,
    updateWindow: '03:00-05:00', timezone: 'UTC', error: null,
  };
  await page.route('**/api/headless/**', async route => {
    const action = new URL(route.request().url()).pathname.split('/').at(-1)!;
    if (route.request().method() === 'POST') {
      actions.push(action);
      if (action === 'update') server.version = server.availableVersion;
      if (action === 'restart') server.serverStartedAt++;
    }
    await route.fulfill({ json: server });
  });
  await page.goto('/browse');
  await waitForShell(page);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  const topbar = page.locator('[data-update-controls]');
  await expect(topbar.getByRole('button', { name: 'Update server', exact: true })).toBeVisible();
  await topbar.getByRole('button', { name: 'Update server', exact: true }).click();
  await expect.poll(() => actions).toEqual(['update']);
  await expect(topbar).toBeHidden();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'About', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Server status' })).toHaveCount(0);
  await expect(page.getByText('Server hosting this library')).toHaveCount(0);
  await page.getByRole('button', { name: 'Stimma Server', exact: true }).click();
  const card = page.getByRole('region', { name: 'Server status' });
  await expect(card.getByText('1.2.4', { exact: true })).toBeVisible();
  await expect(card.getByText('1.0.0', { exact: true })).toBeVisible();
  server.availableVersion = '1.2.5';
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click();
  await card.getByRole('button', { name: 'Update server', exact: true }).click();
  await expect(card.getByText('1.2.5', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Restart server…', exact: true }).click();
  await expect(page.getByText('Connected clients will briefly disconnect.')).toBeVisible();
  await page.getByRole('button', { name: 'Restart server', exact: true }).click();
  await expect.poll(() => actions).toEqual(['update', 'check', 'update', 'restart']);
  await expect(card.getByRole('button', { name: 'Check for updates', exact: true })).toBeEnabled();
  server.bootstrapUpdateRequired = true;
  server.bootstrapUpdateAvailable = true;
  server.latestBootstrapVersion = '2.0.0';
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click();
  await card.getByRole('button', { name: 'Docker update needed', exact: true }).click();
  await expect(card.getByText('docker compose pull', { exact: false })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Update server', exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('headless-settings.png') });
});

test('server update progress survives a client reload and clears only after the new version is ready', async ({ page }) => {
  const server = { headless: true, version: '1.2.3', availableVersion: '1.2.4', status: 'ready', bootstrapVersion: '1.0.0' };
  await page.route('**/api/headless/**', async route => {
    if (route.request().method() === 'POST') server.status = 'downloading';
    await route.fulfill({ json: server });
  });
  await page.goto('/browse');
  await waitForShell(page);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  const controls = page.locator('[data-update-controls]');
  await controls.getByRole('button', { name: 'Update server', exact: true }).click();
  await expect(controls.getByRole('button', { name: 'Downloading update…', exact: true })).toBeVisible();
  await page.removeLocatorHandler(page.getByTestId('readiness-dismiss'));
  await page.reload();
  await waitForShell(page);
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => { await dismiss.click(); });
  await expect(controls.getByRole('button', { name: 'Downloading update…', exact: true })).toBeVisible();
  server.version = '1.2.4';
  server.status = 'starting';
  await expect(controls.getByRole('button', { name: 'Starting…', exact: true })).toBeVisible();
  server.status = 'ready';
  await expect(controls).toBeHidden();
});
