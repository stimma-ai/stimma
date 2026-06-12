import { chromium, type FullConfig } from '@playwright/test'

/**
 * Global setup for the docs screenshot harness.
 *
 * Forces light theme and marks onboarding as completed (both key prefixes,
 * since the app modifier varies between dev and packaged builds), waits for
 * the profile to resolve, then saves storage state for all shot specs.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL || 'http://localhost:9301'
  console.log(`docs-shots setup: ${baseURL}`)

  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()

  await page.addInitScript(() => {
    // Key prefix is the bundle id (see frontend/src/appConfig.js).
    localStorage.setItem('stimma_bundle_id', 'ai.stimma.stimma.debug')
    for (const prefix of ['stimma', 'stimma_ai.stimma.stimma.debug']) {
      localStorage.setItem(`${prefix}_global_theme`, 'light')
      localStorage.setItem(`${prefix}_global_onboarding_completed`, 'true')
    }
  })

  await page.goto(baseURL)
  await page.waitForFunction(() => localStorage.getItem('profileId') !== null, { timeout: 30000 })

  // The one-time post-onboarding feedback coachmark auto-opens the logo menu
  // and persists feedback.coachmark_shown when it fires. Let it fire here so
  // it never appears in a shot.
  await page.waitForTimeout(2500)
  await page.keyboard.press('Escape')

  await context.storageState({ path: 'e2e/docs-shots/.auth/storage-state.json' })
  await browser.close()
  console.log('docs-shots setup: complete')
}
