import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

test('About manages the connected headless server separately from the desktop app', async ({ page }, testInfo) => {
  const actions: string[] = [];
  const server = {
    headless: true, version: '1.2.3', availableVersion: '1.2.4', status: 'ready',
    bootstrapVersion: '1.0.0', latestBootstrapVersion: '1.0.0',
    bootstrapUpdateRequired: false, bootstrapUpdateAvailable: false,
    updateWindow: '03:00-05:00', timezone: 'UTC', error: null,
  };
  await page.route('**/api/headless/**', async route => {
    const action = new URL(route.request().url()).pathname.split('/').at(-1)!;
    if (route.request().method() === 'POST') actions.push(action);
    await route.fulfill({ json: server });
  });
  // The fresh profile's readiness overlay arrives after the shell renders.
  await page.addLocatorHandler(page.getByTestId('readiness-dismiss'), async dismiss => {
    await dismiss.click();
  });
  await page.goto('/browse');
  await waitForShell(page);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'About', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Connected server' })).toBeVisible();
  await expect(page.getByText('1.2.3', { exact: true })).toBeVisible();
  await expect(page.getByText('1.0.0', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Check for updates', exact: true }).click();
  await page.getByRole('button', { name: 'Update server', exact: true }).click();
  await expect(page.getByText(/Connected clients will briefly disconnect/)).toBeVisible();
  await page.getByRole('button', { name: 'Update and restart', exact: true }).click();
  await page.getByRole('button', { name: 'Restart server', exact: true }).click();
  await page.getByRole('button', { name: 'Restart', exact: true }).click();
  expect(actions).toEqual(['check', 'update', 'restart']);
  server.bootstrapUpdateRequired = true;
  server.latestBootstrapVersion = '2.0.0';
  await page.getByRole('button', { name: 'Check for updates', exact: true }).click();
  await expect(page.getByText(/Docker base 2.0.0/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Update server', exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('headless-settings.png') });
});
