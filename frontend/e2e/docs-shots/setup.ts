import { chromium, type FullConfig } from '@playwright/test'

/**
 * Global setup for the docs screenshot harness.
 *
 * Forces light theme and marks onboarding as completed (legacy and current
 * sandbox-scoped key prefixes), waits for
 * the profile to resolve, then saves storage state for all shot specs.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL || 'http://localhost:9301'
  console.log(`docs-shots setup: ${baseURL}`)

  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()

  const bundle = process.env.DOCS_SHOTS_BUNDLE || 'ai.stimma.stimma.debug'
  const sandbox = process.env.DOCS_SHOTS_SANDBOX || 'docs-demo'
  await page.addInitScript(([bundle, sandbox]) => {
    // Keys are prefixed with the bundle id and sandbox (utils/storageKeys.ts).
    localStorage.setItem('stimma_bundle_id', bundle)
    localStorage.setItem('stimma_sandbox', sandbox)
    localStorage.setItem('stimma_install_theme', 'light')
    localStorage.setItem('stimma_install_terms_accepted', JSON.stringify({ version: 999, at: Date.now() }))
    for (const prefix of ['stimma', `stimma_${bundle}`, `stimma_${bundle}_default`, `stimma_${bundle}_${sandbox}`]) {
      localStorage.setItem(`${prefix}_global_onboarding_completed`, '1')
    }
  }, [bundle, sandbox])

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
