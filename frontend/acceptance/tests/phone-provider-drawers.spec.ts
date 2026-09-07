import { expect, test } from '@playwright/test';
import { settleAnyViewport } from '../helpers/viewport';

for (const name of ['ComfyUI', 'Draw Things']) {
  test(`${name} drawer stays interactive and expands without reloading its manager`, async ({ page }) => {
    const id = name === 'ComfyUI' ? 'comfyui' : 'drawthings';
    await page.route('**/api/tools/providers', route => route.fulfill({ json: [{ provider_id: id, provider_name: name, status: 'connected', management_url: '/manage', tools: [] }] }));
    await page.route(`**/api/provider-manage/${id}/**`, route => route.fulfill({ contentType: 'text/html', body: '<meta name="viewport" content="width=device-width,initial-scale=1"><button style="height:48px" onclick="this.textContent=\'Tapped\'">Test manager</button><div style="height:1600px">Scrollable manager</div>' }));
    await page.goto('/home');
    await settleAnyViewport(page);
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--safe-top', '59px');
      document.documentElement.style.setProperty('--safe-bottom', '34px');
    });
    await page.locator('.compact-header').getByTitle(name, { exact: true }).click();
    const panel = page.locator('[data-sheet-layer] .sheet-panel');
    await expect(panel).toBeVisible();
    expect((await panel.boundingBox())!.height).toBeGreaterThan(600);
    const frame = page.frameLocator(`iframe[title="${name} manager"]`);
    await frame.getByRole('button', { name: 'Test manager' }).tap();
    await expect(frame.getByRole('button', { name: 'Tapped' })).toBeVisible();
    await expect(panel).toBeVisible();
    const handle = page.getByRole('button', { name: 'Expand drawer' });
    const box = (await handle.boundingBox())!;
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 195, y: box.y + 22 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 195, y: 80 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await cdp.detach();
    await expect(page.getByRole('button', { name: 'Collapse drawer' })).toBeVisible();
    expect((await panel.boundingBox())!.y).toBeGreaterThanOrEqual(59);
    await expect.poll(async () => (await panel.boundingBox())!.height).toBeGreaterThan(750);
    await expect(frame.getByRole('button', { name: 'Tapped' })).toBeVisible();
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expect(panel).toBeHidden();
    await page.locator('.compact-header').getByTitle(name, { exact: true }).click();
    await page.mouse.click(195, 100);
    await expect(panel).toBeHidden();
  });
}
