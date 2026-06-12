import { test, type Page } from '@playwright/test'
import { resetToolState, settle, shoot } from '../helpers'

/**
 * Post-processing chain shots (docs: tools/post-processing).
 * Stages the chain through the real Add step menu, then runs a generation
 * so the queue shows chain step progress.
 *
 * Tool working state persists server-side, so each test resets it first to
 * stay idempotent across runs.
 */

const FLUX = '/tools/comfyui%3Aflux-dev'
const FLUX_ID = 'comfyui:flux-dev'

async function openFreshTool(page: Page) {
  await page.goto(FLUX)
  await settle(page, 400)
  await resetToolState(page, FLUX_ID)
  await page.reload()
  await settle(page, 400)
  await page.keyboard.press('Escape')
}

/** Menu entries are buttons (step cards are not), so a role-scoped click is
 *  unambiguous even when a card with the same name already exists. */
async function addChainStep(page: Page, name: string) {
  await page.getByRole('button', { name: 'Add step' }).click()
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).first().click()
  await page.waitForTimeout(400)
}

test('add step menu open', async ({ page }) => {
  await openFreshTool(page)
  const header = page.getByText('Post-processing', { exact: true }).first()
  await header.scrollIntoViewIfNeeded()
  // Scroll the panel up a bit so the popover has room below the button.
  await page.mouse.wheel(0, 200)
  await page.getByRole('button', { name: 'Add step' }).click()
  await page.waitForTimeout(400)
  await shoot(page, 'tools/post-processing-add-menu')
})

test('three step chain, one expanded', async ({ page }) => {
  await openFreshTool(page)
  await addChainStep(page, '4x-UltraSharp')
  await addChainStep(page, 'Levels')
  await addChainStep(page, 'Vignette')
  // Expand Levels to show its settings (collapse arrow on the step card).
  await page.getByText('Levels', { exact: true }).first().click()
  await page.waitForTimeout(400)
  await page.getByText('Post-processing', { exact: true }).first().scrollIntoViewIfNeeded()
  await shoot(page, 'tools/post-processing-chain')
})

test('chain progress in queue', async ({ page }) => {
  await openFreshTool(page)
  await addChainStep(page, '4x-UltraSharp')
  await addChainStep(page, 'Vignette')

  const editor = page.locator('.cm-content').first()
  await editor.click()
  await page.keyboard.type('layered dunes at dusk, ember palette')
  await page.getByRole('button', { name: /Run/ }).first().click()
  // Capture mid-chain: wait for the job tile to materialize, then shoot
  // while the chain steps are still running (provider speed is tuned via
  // STIMMA_DEMO_DELAY in run.sh so the chain takes several seconds).
  await page.getByText('No jobs yet').first().waitFor({ state: 'hidden', timeout: 20000 })
  await page.waitForTimeout(1200)
  await shoot(page, 'tools/post-processing-progress')
  // And the finished state for comparison.
  await page.waitForTimeout(15000)
  await settle(page)
  await shoot(page, 'tools/post-processing-done')
})
