import { defineConfig } from '@playwright/test';

// Tier B: the acceptance specs inside the real Electron shell. Same servers,
// same global setup (Chromium seeds the backend + storage-state); the specs
// select the Electron fixtures via STIMMA_ACCEPTANCE_SHELL (set here).
process.env.STIMMA_ACCEPTANCE_SHELL = 'electron';

const frontendPort = process.env.STIMMA_FRONTEND_PORT || '19292';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90000,
  reporter: [
    ['html', { open: 'never', outputFolder: 'acceptance/playwright-report-electron' }],
    ['list'],
  ],
  globalSetup: './helpers/global-setup.ts',
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'electron' }],
});
