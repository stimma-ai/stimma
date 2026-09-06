import { defineConfig, devices } from '@playwright/test';

const frontendPort = process.env.STIMMA_FRONTEND_PORT || '19292';
const slowMo = Number.parseInt(process.env.STIMMA_ACCEPTANCE_SLOW_MO || '0', 10);

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60000,
  reporter: [['html', { open: 'never', outputFolder: 'acceptance/playwright-report' }], ['list']],
  globalSetup: './helpers/global-setup.ts',
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    storageState: 'acceptance/.auth/storage-state.json',
    launchOptions: Number.isFinite(slowMo) && slowMo > 0 ? { slowMo } : undefined,
  },
  projects: [
    // Desktop lane: every spec except the phone-only ones.
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testIgnore: /phone-.*\.spec\.ts/,
    },
    // Phone lane (`stimma test acceptance --viewport=phone`): 390×844, touch,
    // coarse pointer. Runs only the phone-*.spec.ts files, which audit every
    // route for horizontal overflow and sub-44px hit targets and keep a
    // screenshot per route. See DESIGN.md §1.11.
    {
      name: 'phone',
      use: {
        ...devices['iPhone 13'],
        browserName: 'chromium',
        defaultBrowserType: 'chromium',
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
      testMatch: /phone-.*\.spec\.ts/,
    },
  ],
});
