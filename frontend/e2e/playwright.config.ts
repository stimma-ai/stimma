import { defineConfig, devices } from '@playwright/test';

const frontendPort = process.env.STIMMA_FRONTEND_PORT || '9192';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  timeout: 60000,
  reporter: [['html', { open: 'never' }], ['list']],
  globalSetup: './helpers/global-setup.ts',
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    storageState: 'e2e/.auth/storage-state.json',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
