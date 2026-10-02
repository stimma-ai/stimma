import { chromium, type FullConfig } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

export default async function globalSetup(config: FullConfig) {
  const baseURL = String(config.projects[0].use.baseURL || 'http://localhost:19292');
  const browser = await launchSetupBrowser();
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
  });
  // The setup wizard persists its seen version in backend settings. Seed that
  // through the same endpoint used by dismissal; the old localStorage flag no
  // longer suppresses it and can leave a late overlay blocking product tests.
  const setupProfileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const seen = await page.request.post(`${baseURL}/api/settings/setup-wizard-seen`, {
    headers: { 'X-Profile-ID': setupProfileId! },
  });
  if (!seen.ok()) throw new Error(`Could not dismiss acceptance setup wizard: ${seen.status()}`);
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

// Some CI runners intermittently crash the headless shell before it opens a
// page. Retry only that native startup failure; test and navigation failures
// remain failures.
async function launchSetupBrowser() {
  for (let attempt = 0; attempt < 3; attempt++) {
    try { return await chromium.launch(); }
    catch (error) {
      if (!process.env.CI || attempt === 2 || !String(error).includes('Received signal 11')) throw error;
      console.warn('Chromium crashed before acceptance setup; retrying browser launch.');
    }
  }
  throw new Error('Could not launch the acceptance setup browser');
}
