import { expect, type Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'out')

/** Let layout, images, and transitions finish before capturing. */
export async function settle(page: Page, ms = 700) {
  // Bounded: views with live polling (tool view jobs) never reach networkidle.
  await page.waitForLoadState('networkidle', { timeout: 4000 }).catch(() => {})
  // All visible <img> elements decoded.
  await page
    .waitForFunction(
      () => Array.from(document.images).every((img) => img.complete && img.naturalWidth > 0),
      { timeout: 10000 },
    )
    .catch(() => {})
  await page.waitForTimeout(ms)
}

/** Capture the full viewport to out/<name>.png (creates directories). */
export async function shoot(page: Page, name: string) {
  const file = path.join(OUT_DIR, `${name}.png`)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  await page.screenshot({ path: file })
  console.log(`  📸 ${name}`)
}

/** Capture a single element to out/<name>.png. */
export async function shootElement(page: Page, selector: string, name: string) {
  const file = path.join(OUT_DIR, `${name}.png`)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const el = page.locator(selector).first()
  await expect(el).toBeVisible()
  await el.screenshot({ path: file })
  console.log(`  📸 ${name} (element)`)
}

/** Open the Settings modal at a specific section via the app's window event. */
export async function openSettings(page: Page, section: string) {
  await page.evaluate((s) => {
    window.dispatchEvent(new CustomEvent('open-settings', { detail: s }))
  }, section)
  await page.waitForTimeout(400)
}

/**
 * Reset a tool's persisted working state (prompt, params, chain) so shot
 * specs are idempotent across runs. Must be called from a page that has the
 * app loaded (reads profileId from localStorage).
 */
export async function resetToolState(page: Page, fullToolId: string) {
  await page.evaluate(async (toolId) => {
    const profileId = localStorage.getItem('profileId') || ''
    await fetch(`/api/tools/state/${toolId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Profile-ID': profileId },
      body: JSON.stringify({ state: {} }),
    })
  }, fullToolId)
}
