// Every key a client persists must be declared in utils/stateRegistry.ts, on one
// side of the line between the shared workspace and this device.
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { STATE_REGISTRY, isMigratedKey, isMigratedBlobKey, instanceOfKey } from '../src/utils/stateRegistry.ts'

const src = fileURLToPath(new URL('../src', import.meta.url))

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(ts|js|vue)$/.test(entry.name) && !/\.test\./.test(entry.name) ? [path] : []
  })
}

const HELPER = /\bmake(Profile|Storage|Global|Install)Key(?:For)?\(([^\n]*?)\)/g
const TOOL_HELPER = /\bmakeTool(?:Db|Profile)Key\(([^\n]*?)\)/g
const RAW = /\b(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)\(\s*['"`]([^'"`]+)['"`]/g
const KEY_CONST = /\b(?:const|let)\s+\w*(?:KEY|Key)\w*\s*=\s*['"`]([^'"`$]+)['"`]/g

// Files whose constants or helpers name things other than client storage.
const EXEMPT = ['utils/storageKeys.ts', 'utils/installKey.ts', 'utils/stateRegistry.ts']

function literals(args) {
  return [...args.matchAll(/['"]([^'"]+)['"]/g)].map(match => match[1])
}

function foundKeys() {
  const found = new Map()
  const note = (name, file) => { if (!found.has(name)) found.set(name, file) }
  for (const path of sourceFiles(src)) {
    const file = relative(src, path)
    if (EXEMPT.includes(file)) continue
    const text = readFileSync(path, 'utf8')
    for (const match of text.matchAll(HELPER)) {
      const parts = literals(match[2])
      if (parts.length) note(parts.join(':'), file)
    }
    for (const match of text.matchAll(TOOL_HELPER)) {
      note(['tool', ...literals(match[1])].join(':'), file)
    }
    for (const match of text.matchAll(RAW)) note(match[1], file)
    for (const match of text.matchAll(KEY_CONST)) note(match[1], file)
  }
  return found
}

const declared = [...STATE_REGISTRY.shared, ...STATE_REGISTRY.device, ...STATE_REGISTRY.serverPreference]
const isDeclared = name => declared.some(stem => name === stem || name.startsWith(`${stem}:`))

test('every persisted key is declared on one side of the line', () => {
  const undeclared = [...foundKeys()].filter(([name]) => !isDeclared(name))
  assert.deepEqual(undeclared, [], 'Add these to utils/stateRegistry.ts')
})

test('nothing is declared on both sides', () => {
  const shared = new Set(STATE_REGISTRY.shared)
  assert.deepEqual(STATE_REGISTRY.device.filter(stem => shared.has(stem)), [])
})

test('migration takes work and leaves device state and secrets behind', () => {
  for (const key of [
    'tool_comfyui_flux__i_7_state',
    'tool_comfyui_flux__project_3__i_7_ui',
    'tool_comfyui_flux__i_abc123_active_preset',
    'tool_comfyui_flux__i_7_remix',
    'tool_comfyui_flux__i_7_video_images',
    'lorapool_comfyui:flux',
    'lorapool_comfyui:flux__i_7',
    'chat_12_draft',
    'flow_3_program_draft',
    'global_search_recents',
    'send-to-tool_text-to-image_recent',
    'onboarding_completed',
  ]) assert.ok(isMigratedKey(key), key)
  for (const key of [
    'pin_cache',
    'sidebar_width',
    'last_route',
    'browse_filters',
    'media_playback_settings',
    'workspace_tabs',
    'workspace_tabs_last_library_route',
    'tool_comfyui_flux_state', // Pre-instance leftover.
    'tool_comfyui_flux__i_7_global', // Retired duplicate.
    'tool_comfyui_flux__i_7_pending_input',
    'mask_editor_brush_size', // Never survived a restart, so nothing to carry.
  ]) assert.ok(!isMigratedKey(key), key)
  assert.ok(isMigratedBlobKey('tool_comfyui_flux__i_7_mask'))
  assert.ok(isMigratedBlobKey('tool_comfyui_flux__i_7_paint_0'))
  assert.ok(!isMigratedBlobKey('tool_comfyui_flux__i_7_pending_generation_mask'))
})

test('a key names the tool tab it belongs to', () => {
  assert.equal(instanceOfKey('tool_x__project_3__i_7_state'), '7')
  assert.equal(instanceOfKey('tool_x__i_mf3ab90_state'), 'mf3ab90')
  assert.equal(instanceOfKey('lorapool_a:b__i_7'), '7')
  assert.equal(instanceOfKey('lorapool_a:b__i_image-stack-12'), null)
  assert.equal(instanceOfKey('lorapool_a:b'), null)
})
