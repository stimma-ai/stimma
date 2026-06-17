import { test } from '@playwright/test'
import { openSettings, settle, shoot } from '../helpers'

/**
 * Settings shots (docs: tools/building-providers, tools/stp,
 * prompt-engineering/stimpack, local-ai/llms, local-ai/index).
 * Uses the app's `open-settings` window event to land on a section.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/browse')
  await settle(page, 400)
  await page.keyboard.press('Escape')
})

test('settings: tool providers', async ({ page }) => {
  await openSettings(page, 'tools')
  await settle(page, 500)
  await shoot(page, 'settings/tool-providers')
})

test('settings: stimpacks', async ({ page }) => {
  await openSettings(page, 'stimpacks')
  await settle(page, 800)
  await shoot(page, 'settings/stimpacks')
})

test('settings: llm services (advanced)', async ({ page }) => {
  test.setTimeout(180000)
  await openSettings(page, 'ai-services')
  await settle(page, 500)
  // Run the endpoint capability test so the badges (text, thinking, tools,
  // vision) are in frame. First run loads the model, so allow a while.
  const testButton = page.getByText(/Test connection|Re-test/i).first()
  if (await testButton.isVisible().catch(() => false)) {
    await testButton.click()
    await page
      .getByText(/Ready|failed/i)
      .first()
      .waitFor({ state: 'visible', timeout: 150000 })
      .catch(() => {})
    await page.waitForTimeout(500)
  }
  await shoot(page, 'settings/llm-services')
})

test('settings: agent', async ({ page }) => {
  await openSettings(page, 'agent')
  await settle(page, 500)
  await shoot(page, 'settings/agent')
})
