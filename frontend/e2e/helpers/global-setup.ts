import { chromium, type FullConfig } from '@playwright/test';

/**
 * Global setup that runs once before all tests.
 * Navigates to the app to trigger profile auto-detection,
 * then saves the browser storage state (with profileId in localStorage).
 * If STIMMA_TEST_PROVIDER is set, also waits for test tools to be available.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL || 'http://localhost:9192';
  console.log(`Global setup: navigating to ${baseURL}`);

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  // Navigate to the app - it will auto-detect and set the profile
  await page.goto(baseURL);
  console.log('Global setup: page loaded, waiting for profileId...');

  // Wait for profileId to be set in localStorage
  await page.waitForFunction(() => {
    return localStorage.getItem('profileId') !== null;
  }, { timeout: 30000 });
  console.log('Global setup: profileId detected');

  // If test provider is enabled, wait for test tools to be registered
  // (deferred init runs after server starts, so tools may not be immediately available)
  if (process.env.STIMMA_TEST_PROVIDER) {
    const backendPort = process.env.STIMMA_BACKEND_PORT || '9191';
    const toolsUrl = `http://localhost:${backendPort}/api/tools/providers/tools`;
    console.log(`Global setup: waiting for test tools at ${toolsUrl}`);

    // Poll until test tool appears in the tools list
    const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
    const headers: Record<string, string> = {};
    if (profileId) headers['X-Profile-ID'] = profileId;

    const startTime = Date.now();
    const timeout = 60000;
    while (Date.now() - startTime < timeout) {
      try {
        const resp = await fetch(toolsUrl, { headers });
        if (resp.ok) {
          const tools = await resp.json();
          const hasTestTool = tools.some((t: any) => t.full_tool_id?.includes('test:'));
          if (hasTestTool) {
            console.log('Global setup: test provider tools are available');
            break;
          }
        }
      } catch {
        // Server not ready yet
      }
      await new Promise(r => setTimeout(r, 500));
    }

    if (Date.now() - startTime >= timeout) {
      console.warn('Global setup: timed out waiting for test provider tools');
    }
  }

  // Save the storage state for all tests to reuse
  await context.storageState({ path: 'e2e/.auth/storage-state.json' });
  await browser.close();
  console.log('Global setup: complete');
}
