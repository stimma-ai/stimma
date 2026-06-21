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
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
