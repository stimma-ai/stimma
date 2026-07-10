import { chromium, type FullConfig } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

export default async function globalSetup(config: FullConfig) {
  const baseURL = String(config.projects[0].use.baseURL || 'http://localhost:19292');
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto(baseURL);
  await page.waitForFunction(() => localStorage.getItem('profileId') !== null, null, {
    timeout: 30000,
  });
  await page.waitForFunction(() => localStorage.getItem('stimma_bundle_id'), null, {
    timeout: 30000,
  });
  await page.evaluate(() => {
    const bundleId = localStorage.getItem('stimma_bundle_id') || '';
    const sandbox = localStorage.getItem('stimma_sandbox') || 'default';
    const profileId = localStorage.getItem('profileId') || 'profile-acceptance';
    const prefix = bundleId ? `stimma_${bundleId}_${sandbox}` : 'stimma';
    localStorage.setItem(`${prefix}_global_onboarding_completed`, '1');
    localStorage.setItem(`${prefix}_${profileId}_last_route`, '/browse');
    // The acceptance provider supplies deterministic generation without a
    // user-configured provider, so keep the readiness reminder out of the
    // browser state used for product-flow tests.
    localStorage.setItem(`${prefix}_${profileId}_readiness_panel_dont_show`, '1');
  });
  await page.goto(`${baseURL}/browse`);
  await page.waitForURL(/\/browse/, { timeout: 10000 });

  if (process.env.STIMMA_TEST_PROVIDER) {
    const backendURL = process.env.STIMMA_ACCEPTANCE_BACKEND_URL || 'http://localhost:19291';
    const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
    const headers: Record<string, string> = {};
    if (profileId) headers['X-Profile-ID'] = profileId;

    await waitFor(async () => {
      const resp = await fetch(`${backendURL}/api/tools/providers/tools`, { headers });
      if (!resp.ok) return false;
      const tools = await resp.json();
      return tools.some((tool: any) => tool.full_tool_id === 'test:text-to-image:test-model');
    }, 60000);
  }

  await mkdir('acceptance/.auth', { recursive: true });
  await context.storageState({ path: 'acceptance/.auth/storage-state.json' });
  await browser.close();
}

async function waitFor(check: () => Promise<boolean>, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error('Timed out waiting for acceptance precondition');
}
