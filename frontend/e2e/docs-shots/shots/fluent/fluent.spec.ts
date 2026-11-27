import { expect, test, type Page } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'
import { OUT_DIR, resetToolState, settle, shoot, shootAround } from '../../helpers'

/**
 * Fluent shots (docs: getting-started, prompt-engineering/fluent, tools/assistant).
 *
 * Runs against a real chat model and a real image tool (`run.sh fluent shoot`): the slot
 * rows, the picker's variants and the images are what the model and tool made. Shots run
 * in order on one page, so the picker and Use frames show the images the hero run made.
 *
 * DOCS_SHOTS_IMAGE_TOOL names the tool (README.md). The prompt suits a photographic model.
 */

const TOOL_ID = process.env.DOCS_SHOTS_IMAGE_TOOL || ''
const PROMPT =
  'A young <barista> laughing behind the counter of a small Lisbon café, ' +
  '{an espresso|a pastel de nata} on the marble bar, <time of day> light through the window'

test.describe.configure({ mode: 'serial' })

let page: Page

test.beforeAll(async ({ browser }, info) => {
  test.skip(!TOOL_ID, 'DOCS_SHOTS_IMAGE_TOOL is not set')
  // One page for the whole set, with the project's options (theme, size, saved storage).
  const use = info.project.use
  page = await browser.newPage({
    baseURL: use.baseURL, storageState: use.storageState, viewport: use.viewport,
    deviceScaleFactor: use.deviceScaleFactor, colorScheme: use.colorScheme, locale: 'en-US',
  })
})

test.afterAll(async () => {
  await page?.close()
})

/** The panel's empty space: clicking it leaves the editor without opening anything. */
async function clickAway() {
  const panel = await page.locator('[data-slot-list]').first().boundingBox()
  await page.mouse.click((panel?.x ?? 300) + 40, 900)
}

/** Every slot row has its count and the suggestions have landed. */
async function rowsReady(slots: number) {
  await page.waitForFunction((n) => {
    const list = document.querySelector('[data-slot-list]')
    if (!list) return false
    const rows = list.querySelectorAll('[data-row]')
    return rows.length >= n && !list.querySelector('.fluent-shimmer') && !list.querySelector('[data-suggest-loading]') &&
      !list.querySelector('[data-more-spinner]')
  }, slots, { timeout: 240000 })
}

/** Run once and wait for its image on the stage. */
async function runAndWait() {
  const generating = page.getByText('Generating…').first()
  await page.getByRole('button', { name: /^Run/ }).first().click()
  await expect(generating).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('Generating…')).toHaveCount(0, { timeout: 300000 })
}

test('tool view with a Fluent prompt', async () => {
  await page.goto(`/tools/${encodeURIComponent(TOOL_ID)}`)
  await settle(page, 1500)
  // The image tool's first-connect hint: opening its manager once retires it for good.
  const hint = page.getByRole('button', { name: /^Open / })
  if (await hint.isVisible().catch(() => false)) {
    await hint.click()
    await page.waitForTimeout(500)
    await page.mouse.click(700, 700)
  }
  await resetToolState(page, TOOL_ID)
  await page.reload()
  await settle(page, 1500)
  await page.keyboard.press('Escape')

  // The prompt lives in the workspace, not the tool state: replace it whole. Inserted at
  // once, so the editor's bracket pairing doesn't double what's typed.
  await page.locator('.cm-content').first().click()
  await page.keyboard.press('ControlOrMeta+A')
  await page.keyboard.press('Backspace')
  await page.keyboard.insertText(PROMPT)
  await clickAway()
  await rowsReady(3)
  await page.waitForTimeout(1000)

  // The prompt and its rows, cropped to the panel.
  await shootAround(page, ['.cm-content', '[data-slot-list]', '[data-fluent-chip]'], 'prompt-engineering/fluent-editor', 14)

  // Two images, so the history shows the slots doing their work.
  await runAndWait()
  await runAndWait()
  await settle(page, 1500)
  await shoot(page, 'getting-started/first-generation')
})

test('prompt menu open', async () => {
  await page.locator('[data-fluent-chip]').click()
  await page.waitForTimeout(700)
  await shootAround(page, ['[data-fluent-chip]', '[data-fluent-menu]', '.cm-content'], 'prompt-engineering/fluent-menu', 14)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
})

test('a slot picker open', async () => {
  await page.locator('[data-row]').first().click()
  await page.waitForSelector('[data-picker-body] [data-variant]', { timeout: 120000 })
  await page.waitForTimeout(1200)
  // Descent narrowed to the café's own town, so the person rows show a pick and the ideas
  // stay on the barista the prompt is about.
  await page.locator('[data-filter="descent"]').click()
  await page.getByPlaceholder('Search').last().fill('Portuguese')
  await page.locator('[data-heritage="Portuguese"]').first().click()
  await page.locator('[data-back]').click()
  await page.waitForSelector('[data-picker-body] [data-variant]', { timeout: 120000 })
  await page.waitForFunction(() => !document.querySelector('[data-writing-more]'), null, { timeout: 240000 })
  await page.waitForTimeout(1200)
  // Two ticked: the row says how many of the ideas are in play, with Clear.
  const variants = page.locator('[data-picker-body] [data-variant]')
  await variants.nth(1).click()
  await variants.nth(3).click()
  await page.waitForSelector('[data-of]')
  await page.waitForTimeout(800)
  await shootAround(page, ['.cm-content', '[data-slot-list]'], 'prompt-engineering/fluent-picker', 14)
  // Back to any, so the rest of the set draws freely.
  await page.locator('[data-clear]').click()
  await page.waitForTimeout(300)
  await page.locator('[data-row]').first().click()
  await page.waitForTimeout(500)
})

test('use on a result', async () => {
  await page.locator('[data-use-button]').first().click()
  await page.waitForSelector('[data-use-list]')
  await page.waitForTimeout(700)
  await shoot(page, 'prompt-engineering/fluent-use')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
})

test('the chat bar at work', async ({ browser }, info) => {
  // Its own page, recording: the docs page shows the turn as a short video. A turn's reply
  // isn't kept on screen, so the still is the request typed in the bar.
  const use = info.project.use
  const videoDir = path.join(OUT_DIR, '.video')
  const ctx = await browser.newContext({
    baseURL: use.baseURL, storageState: use.storageState, viewport: use.viewport,
    deviceScaleFactor: use.deviceScaleFactor, colorScheme: use.colorScheme, locale: 'en-US',
    recordVideo: { dir: videoDir, size: { width: 1480, height: 940 } },
  })
  const chat = await ctx.newPage()
  await chat.goto(`/tools/${encodeURIComponent(TOOL_ID)}`)
  await settle(chat, 2500)
  const input = chat.getByPlaceholder(/dramatic/i).first()
  await input.click()
  await input.pressSequentially('Make it a rainy evening and run it', { delay: 45 })
  await chat.waitForTimeout(600)
  await shoot(chat, 'tools/tool-assistant')
  await chat.keyboard.press('Enter')
  // The turn ends with the prompt changed (Undo comes on) and a new image.
  await expect(chat.getByRole('button', { name: 'Undo' }).first()).toBeEnabled({ timeout: 240000 })
  await expect(chat.getByText('Generating…').first()).toBeVisible({ timeout: 120000 }).catch(() => {})
  await expect(chat.getByText('Generating…')).toHaveCount(0, { timeout: 300000 })
  await settle(chat, 2500)
  await shoot(chat, 'tools/tool-assistant-done')
  const video = chat.video()
  await ctx.close()
  if (video) {
    fs.mkdirSync(path.join(OUT_DIR, 'tools'), { recursive: true })
    await video.saveAs(path.join(OUT_DIR, 'tools', 'tool-assistant.webm'))
    await video.delete()
    console.log('  🎬 tools/tool-assistant.webm')
  }
})
