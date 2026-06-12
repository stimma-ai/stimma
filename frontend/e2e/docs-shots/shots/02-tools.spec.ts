import { test, type Page } from '@playwright/test'
import { resetToolState, settle, shoot } from '../helpers'

/**
 * Tool panel shots (docs: tools/tool-panel, tools/index, getting-started).
 * Tool working state persists server-side; tests reset it for idempotence.
 */

const FLUX = '/tools/comfyui%3Aflux-dev'
const FLUX_ID = 'comfyui:flux-dev'

async function dismissOverlays(page: Page) {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
}

async function openFreshTool(page: Page) {
  await page.goto(FLUX)
  await settle(page, 400)
  await resetToolState(page, FLUX_ID)
  await page.reload()
  await settle(page)
  await dismissOverlays(page)
}

test('all tools view', async ({ page }) => {
  await page.goto('/tools')
  await settle(page)
  await dismissOverlays(page)
  await shoot(page, 'tools/all-tools')
})

test('tool panel with prompt', async ({ page }) => {
  await openFreshTool(page)
  // Type a prompt into the CodeMirror editor.
  const editor = page.locator('.cm-content').first()
  await editor.click()
  await page.keyboard.type('flowing gradient study, teal into amber, soft morning light')
  // Expand the Advanced group so steps/guidance/sampler are in frame.
  await page.getByRole('button', { name: /advanced/i }).first().click()
  await page.waitForTimeout(600)
  await shoot(page, 'tools/tool-panel-flux')
})

test('tool picker open', async ({ page }) => {
  await openFreshTool(page)
  // The tool header button opens the hop-to-tool menu.
  await page.getByText('Flux Dev', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await shoot(page, 'tools/tool-picker-open')
})

test('first generation on stage', async ({ page }) => {
  await openFreshTool(page)
  const editor = page.locator('.cm-content').first()
  await editor.click()
  await page.keyboard.type('soft glow field, slate and gold accents, quiet horizon')
  await page.getByRole('button', { name: /Run/ }).first().click()
  // Demo provider takes ~1s; ingestion a few more. Wait for the stage image.
  await page.waitForTimeout(18000)
  await settle(page)
  await shoot(page, 'getting-started/first-generation')
})
