import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

const base = config({})
const built = await build({ ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: { entry: fileURLToPath(new URL('./fixtures/chatModelPicker.ts', import.meta.url)), name: 'ChatModelPickerTest', formats: ['iife'] } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

const route = (slug, source, extra) => ({ slug, source, name: 'GPT-6.1 Sol', model_vendor: 'openai', available: true, status: 'available', ...extra })
const chatgpt = route('chatgpt-1:gpt-6.1-sol', 'provider', { provider_kind: 'chatgpt', provider_name: 'ChatGPT', description: 'via ChatGPT' })
const key = route('openai-1:gpt-6.1-sol', 'provider', { provider_kind: 'openai', provider_name: 'OpenAI', description: 'via OpenAI', collapsed: true, preferred_slug: chatgpt.slug })
const cloud = route('stimma:gpt-6.1-sol', 'stimma_cloud', { cost_tier: '$$$', collapsed: true, preferred_slug: chatgpt.slug })
const auto = { slug: 'auto', source: 'auto', name: 'Auto: GPT-6.1 Sol', available: true, status: 'available', resolved_slug: chatgpt.slug }

async function boot(t, { modelSlug = null, roles = {} } = {}) {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage()
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<div id="app"></div><div id="settings"></div>' })
    if (path.endsWith('/models/available')) return route.fulfill({ json: { models: [auto, cloud, key, chatgpt], global_default: 'auto', cloud_status: 'available', llm_configured: true } })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat-model-picker.test/')
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await page.evaluate(([slug, pins]) => { window.pickerTest.modelSlug = slug; window.pickerTest.roles = pins }, [modelSlug, roles])
  return page
}

async function openPicker(t, options) {
  const page = await boot(t, options)
  await page.locator('#app button').click()
  return { page, dialog: page.getByRole('dialog', { name: 'Choose a model' }) }
}

const rows = dialog => dialog.getByRole('button', { name: /GPT-6\.1 Sol/ })
const disclosure = dialog => dialog.getByRole('button', { name: /Same models on other accounts/ })

test('one row per model until the other accounts are asked for', async t => {
  const { dialog } = await openPicker(t)
  await expect(rows(dialog)).toHaveCount(1)
  await expect(rows(dialog)).toContainText('via ChatGPT')
  await expect(disclosure(dialog)).toContainText('(2)')

  await disclosure(dialog).click()
  await expect(rows(dialog)).toHaveCount(3)
  await expect(rows(dialog).nth(1)).toContainText('Uses your OpenAI balance')
  await expect(rows(dialog).nth(2)).toContainText('Uses Stimma Account credits')
})

test('a chat pinned to a tucked-away route opens showing its check', async t => {
  const { dialog } = await openPicker(t, { modelSlug: cloud.slug })
  await expect(rows(dialog)).toHaveCount(3)
  await expect(rows(dialog).nth(2).locator('svg path[d^="m4.5 12.75"]')).toHaveCount(1)
})

test('search reaches every route', async t => {
  const { dialog } = await openPicker(t)
  await dialog.getByRole('searchbox').fill('stimma')
  await expect(rows(dialog)).toHaveCount(1)
  await expect(rows(dialog)).toContainText('Uses Stimma Account credits')
})

test('a recent on a tucked-away route comes back on the route the list leads with', async t => {
  const { page, dialog } = await openPicker(t)
  await disclosure(dialog).click()
  await rows(dialog).nth(2).click()
  await page.evaluate(() => { window.pickerTest.modelSlug = null })
  await page.locator('#app button').click()
  await expect(rows(dialog)).toHaveCount(1)
  await expect(rows(dialog)).toContainText('via ChatGPT')
  await expect(dialog.getByText('Recent')).toBeVisible()
})

test('settings offer one route, plus the one a row is already pinned to', async t => {
  // Quick tasks is the first row.
  const page = await boot(t, { roles: { quick_task: cloud.slug } })
  await page.locator('#settings button').first().click()
  await expect(page.getByText('Uses Stimma Account credits')).toHaveCount(1)
  await expect(page.getByText('Uses your OpenAI balance')).toHaveCount(0)
})
