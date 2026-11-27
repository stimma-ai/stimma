import { defineConfig, devices } from '@playwright/test'

/**
 * Docs screenshot harness. Captures documentation screenshots against the
 * docs-demo sandbox (seeded by scripts/docs-shots/seed.py).
 *
 * Run via scripts/docs-shots/run.sh — it boots the sandbox backend + Vite
 * and then invokes this project. Output lands in e2e/docs-shots/out/.
 *
 * Conventions:
 * - light theme (set in setup.ts via localStorage before load)
 * - 1480x940 viewport at deviceScaleFactor 2 (crisp retina PNGs)
 * - shot files named <section>/<shot-id>.png matching SHOTS.md log
 */
const frontendPort = process.env.STIMMA_FRONTEND_PORT || '9301'
// Two sets (run.sh): the seeded demo library, and Fluent against a real chat model and
// image tool (shots/fluent/). Each run shoots one set.
const fluentSet = process.env.DOCS_SHOTS_SET === 'fluent'

export default defineConfig({
  testDir: './shots',
  ...(fluentSet ? { testMatch: 'fluent/**/*.spec.ts' } : { testIgnore: 'fluent/**' }),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Real models take their time: Fluent writes each slot's ideas, then the image tool runs.
  timeout: fluentSet ? 600000 : 120000,
  reporter: [['list']],
  globalSetup: './setup.ts',
  outputDir: './.artifacts',
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    storageState: 'e2e/docs-shots/.auth/storage-state.json',
    viewport: { width: 1480, height: 940 },
    deviceScaleFactor: 2,
    colorScheme: 'light',
    actionTimeout: 15000,
    navigationTimeout: 30000,
  },
  projects: [
    { name: 'docs-shots', use: { ...devices['Desktop Chrome'], viewport: { width: 1480, height: 940 }, deviceScaleFactor: 2 } },
  ],
})
