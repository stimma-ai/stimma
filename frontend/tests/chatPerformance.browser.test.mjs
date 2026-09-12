import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'
import config from '../vite.config.js'

// Instrument the real view only in this in-memory test build. Count actual
// render work rather than assert fragile wall-clock thresholds on CI machines.
const instrument = {
  name: 'chat-performance-observer', enforce: 'pre',
  transform(source, id) {
    if (!id.endsWith('/src/views/ChatView.vue')) return
    for (const name of ['getActivityGroupSummary', 'renderMarkdownUncached', 'parseMarkdownSegmentsUncached', 'getDisplayText']) {
      const pattern = new RegExp(`function ${name}\\(([^)]*)\\) \\{`)
      assert.match(source, pattern, `missing performance instrumentation target: ${name}`)
      source = source.replace(pattern, `$&\nwindow.chatCounts['${name}'] = (window.chatCounts['${name}'] || 0) + 1`)
    }
    return source.replace('</script>', `defineExpose({ items, messageInput, agentRunning, getActivityGroupSummary, activityGroupInfo, parsedUserMessage, parseMarkdownSegments, renderMarkdown, textRenderCache, expandedActivityGroups, brokenMediaIds, showStopButton, modelsFetched, messageQueue, messageHistory, scrollToBottom, getDelegateActivitySummary, getDelegateActivityItems })\n</script>`)
  },
}
const base = config({})
const built = await build({
  ...base, configFile: false, logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  plugins: [instrument, ...base.plugins],
  define: { ...base.define, 'process.env.NODE_ENV': '"production"' },
  build: { write: false, minify: false, lib: {
    entry: fileURLToPath(new URL('./fixtures/chatPerformance.ts', import.meta.url)), name: 'ChatPerformanceTest', formats: ['iife'],
  } },
})
const output = (Array.isArray(built) ? built : [built]).flatMap(result => result.output)

test('long chat typing does not render history; updates and edits remain live', async t => {
  const browser = await chromium.launch()
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  const errors = []
  const sentMessages = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="app" style="height:850px"></div></body></html>' })
    if (path === '/api/chats/1') return route.fulfill({ json: { id: 1, name: 'Performance fixture', model_slug: 'test', generation_settings: { auto_delete_duration: 'never' } } })
    if (path.endsWith('/items')) {
      if (route.request().method() === 'POST') sentMessages.push(route.request().postDataJSON())
      return route.fulfill({ json: { items: [], has_more: false } })
    }
    if (path === '/api/models/available') return route.fulfill({ json: { models: [{ slug: 'test', name: 'Test', available: true, selectable: true, source: 'endpoint' }], global_default: 'test', cloud_status: 'available', llm_configured: true } })
    if (path.includes('skills') || path.includes('markers')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  await page.goto('http://chat.test/')
  await page.evaluate(() => { window.chatCounts = {} })
  for (const asset of output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css'))) await page.addStyleTag({ content: String(asset.source) })
  await page.addScriptTag({ content: output.find(item => item.type === 'chunk').code })
  await expect.poll(() => page.evaluate(() => window.chatTest?.modelsFetched)).toBe(true)
  await expect(page.locator('textarea')).toBeVisible()
  await page.evaluate(() => {
    const items = []
    for (let turn = 0; turn < 500; turn++) {
      const id = turn * 4 + 1
      items.push(
        { id, item_type: 'user_message', message_text: `Question ${turn}` },
        { id: id + 1, item_type: 'tool_call', tool_name: 'bash', tool_call_id: `call-${turn}`, tool_args: { command: 'echo hello' } },
        { id: id + 2, item_type: 'tool_result', tool_call_id: `call-${turn}`, tool_result: { output: 'hello' } },
        { id: id + 3, item_type: 'assistant_message', message_text: `**Answer ${turn}** with [a link](https://example.com).` },
      )
    }
    window.chatTest.items = items
  })
  await expect(page.getByText('Answer 499', { exact: true })).toHaveCount(1)
  await page.evaluate(() => { window.chatCounts = {} })
  await page.locator('textarea').pressSequentially('Typing stays responsive', { delay: 10 })
  assert.equal(await page.evaluate(() => window.chatTest.messageInput), 'Typing stays responsive')
  assert.deepEqual(await page.evaluate(() => window.chatCounts), {}, 'typing must not evaluate transcript helpers')
  await page.evaluate(() => {
    const last = window.chatTest.items.at(-1)
    window.chatTest.items[window.chatTest.items.length - 1] = { ...last, message_text: '**Streamed update**' }
  })
  await expect(page.getByText('Streamed update', { exact: true })).toHaveCount(1)
  assert.equal(await page.evaluate(() => window.chatCounts.renderMarkdownUncached), 1, 'only changed Markdown is parsed')
  assert.equal(await page.locator('.chat-item').first().evaluate(el => getComputedStyle(el).contentVisibility), 'auto')
  assert.equal(await page.locator('.chat-item').nth(2).evaluate(el => getComputedStyle(el).contentVisibility), 'visible', 'hidden tool results do not reserve phantom row height')
  await page.evaluate(() => window.chatTest.scrollToBottom())
  await expect(page.getByText('Streamed update', { exact: true })).toBeInViewport()
  await page.getByText('Question 0', { exact: true }).scrollIntoViewIfNeeded()
  await expect(page.getByText('Question 0', { exact: true })).toBeInViewport()
  await page.evaluate(() => window.chatTest.scrollToBottom())
  await expect(page.getByText('Streamed update', { exact: true })).toBeInViewport()

  assert.equal(await page.evaluate(() => {
    const chat = window.chatTest
    const group = chat.activityGroupInfo.get(1998)
    return chat.getActivityGroupSummary(group) === chat.getActivityGroupSummary(group)
  }), true, 'summary is shared across its template call sites')
  await page.evaluate(() => {
    const chat = window.chatTest
    chat.items[1998] = { ...chat.items[1998], tool_result: { error: 'failed' } }
  })
  assert.equal(await page.evaluate(() => {
    const chat = window.chatTest
    return chat.getActivityGroupSummary(chat.activityGroupInfo.get(1998)).hasFailed
  }), true, 'a new tool result invalidates the summary')

  assert.deepEqual(await page.evaluate(() => {
    const item = { id: 9000, message_text: 'Before' }
    const before = window.chatTest.parsedUserMessage(item).text
    item.message_text = 'Edited'
    return [before, window.chatTest.parsedUserMessage(item).text]
  }), ['Before', 'Edited'], 'same-length edits cannot return stale text')
  await page.evaluate(() => window.setChatTheme('dark'))
  const darkCode = await page.evaluate(() => window.chatTest.renderMarkdown('```python\nreturn 123\n```'))
  await page.evaluate(() => window.setChatTheme('light'))
  const lightCode = await page.evaluate(() => window.chatTest.renderMarkdown('```python\nreturn 123\n```'))
  assert.match(darkCode, /text-blue-300/)
  assert.match(lightCode, /text-blue-700/)
  const sanitized = await page.evaluate(() => window.chatTest.renderMarkdown('<img src="x" onerror="alert(1)"><script>alert(1)</script>'))
  assert.doesNotMatch(sanitized, /onerror|<script/)

  await page.evaluate(() => { window.chatTest.messageInput = 'Restored draft' })
  await expect(page.locator('textarea')).toHaveValue('Restored draft')
  await page.locator('textarea').press('Shift+Enter')
  await expect(page.locator('textarea')).toHaveValue('Restored draft\n')
  await page.locator('textarea').press('Enter')
  await expect.poll(() => sentMessages.length).toBe(1)
  assert.equal(sentMessages[0].message_text, 'Restored draft')
  await expect(page.locator('textarea')).toHaveValue('')
  await page.locator('textarea').press('ArrowUp')
  await expect(page.locator('textarea')).toHaveValue('Restored draft')
  await page.locator('textarea').press('End')
  await page.locator('textarea').press('ArrowDown')
  await expect(page.locator('textarea')).toHaveValue('')
  await page.locator('textarea').fill('Queued while streaming')
  await page.locator('textarea').press('Enter')
  await expect(page.locator('textarea')).toHaveValue('')
  assert.equal(await page.evaluate(() => window.chatTest.messageQueue[0].text), 'Queued while streaming')

  await page.evaluate(() => window.mountLegacyComposer())
  const textarea = page.locator('textarea')
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled()
  await textarea.fill('Legacy v-model')
  assert.equal(await page.evaluate(() => window.legacyDraft.value), 'Legacy v-model')
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled()
  await textarea.fill('A long draft\n'.repeat(30))
  await expect.poll(() => textarea.evaluate(el => parseFloat(el.style.height))).toBeGreaterThan(400)
  await page.evaluate(() => { window.legacyDraft.value = 'Programmatic replacement' })
  await expect(textarea).toHaveValue('Programmatic replacement')
  await expect.poll(() => textarea.evaluate(el => parseFloat(el.style.height))).toBeLessThan(100)
  assert.deepEqual(errors, [])
})
