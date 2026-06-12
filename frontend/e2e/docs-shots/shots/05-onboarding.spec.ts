import { test } from '@playwright/test'
import { settle, shoot } from '../helpers'

/**
 * First-run onboarding shot (docs: getting-started).
 * Uses a clean storage state so the onboarding gate engages, with the
 * theme forced light via init script.
 */

test.use({ storageState: { cookies: [], origins: [] } })

test('onboarding screen', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('stimma_bundle_id', 'ai.stimma.stimma.debug')
    localStorage.setItem('stimma_ai.stimma.stimma.debug_global_theme', 'light')
    localStorage.setItem('stimma_global_theme', 'light')
  })
  await page.goto('/')
  await page.waitForURL(/onboarding/, { timeout: 15000 })
  await settle(page)
  await shoot(page, 'getting-started/onboarding')
})
