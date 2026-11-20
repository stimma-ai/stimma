import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import type { BrowserWindow } from 'electron'
import { createHyprlandIdleInhibitor, onHyprland, pickWindowAddress } from '../src/hyprlandIdle.ts'

test('only Hyprland on Linux is touched', () => {
  assert.equal(onHyprland({ HYPRLAND_INSTANCE_SIGNATURE: 'abc' }, 'linux'), true)
  assert.equal(onHyprland({}, 'linux'), false)
  assert.equal(onHyprland({ HYPRLAND_INSTANCE_SIGNATURE: 'abc' }, 'darwin'), false)
})

test('picks this process\'s window, by title when it has several, never a guess', () => {
  const clients = [
    { address: '0xa', pid: 7, title: 'Stimma — A' },
    { address: '0xb', pid: 7, title: 'Stimma — B' },
    { address: '0xc', pid: 9, title: 'Stimma — B' },
  ]
  assert.equal(pickWindowAddress(clients, 7, 'Stimma — A'), '0xa')
  assert.equal(pickWindowAddress(clients.slice(0, 1), 7, 'renamed', true), '0xa')
  assert.equal(pickWindowAddress(clients.slice(0, 1), 7, 'renamed', false), null, 'a hidden sender never claims the other window')
  assert.equal(pickWindowAddress(clients, 8, 'Stimma — A'), null)
  assert.equal(pickWindowAddress([...clients, { address: '0xd', pid: 7, title: 'Stimma — A' }], 7, 'Stimma — A'), null)
  assert.equal(pickWindowAddress([{ address: "0x1'); evil()", pid: 7, title: 't' }], 7, 't'), null)
})

function fakeWindow() {
  const webContents = new EventEmitter()
  return Object.assign(new EventEmitter(), {
    webContents,
    getTitle: () => 'Stimma',
    isDestroyed: () => false,
    isVisible: () => true,
  }) as unknown as BrowserWindow & { webContents: EventEmitter }
}

test('sets and clears idle_inhibit on the window, skipping repeats, and clears on reload', async () => {
  const calls: string[][] = []
  const run = async (args: string[]) => {
    calls.push(args)
    if (args[0] === '-j') return JSON.stringify([{ address: '0x5e', pid: 42, title: 'Stimma' }])
    return 'true\n'
  }
  const set = createHyprlandIdleInhibitor(run, 42)
  const win = fakeWindow()
  await set(win, true)
  await set(win, true)
  const scripts = () => calls.filter((c) => c[0] === 'repl').map((c) => c[1].match(/address:(\w+)', prop='idle_inhibit', value='(\d)'/)?.slice(1).join(' '))
  assert.deepEqual(scripts(), ['0x5e 1'])
  win.webContents.emit('did-navigate')
  await set(win, false)
  assert.deepEqual(scripts(), ['0x5e 1', '0x5e 0'])
  assert.equal(calls.filter((c) => c[0] === '-j').length, 1, 'address is looked up once')
})

test('turning off while turning on is in flight still turns it off', async () => {
  const sent: string[] = []
  let release: () => void = () => {}
  const run = async (args: string[]) => {
    if (args[0] === '-j') return JSON.stringify([{ address: '0x5e', pid: 42, title: 'Stimma' }])
    sent.push(args[1].includes("value='1'") ? 'on' : 'off')
    if (sent.length === 1) await new Promise<void>((resolve) => { release = resolve })
    return 'true'
  }
  const set = createHyprlandIdleInhibitor(run, 42)
  const win = fakeWindow()
  const on = set(win, true)
  await new Promise((resolve) => setImmediate(resolve))
  const off = set(win, false)
  release()
  await Promise.all([on, off])
  assert.deepEqual(sent, ['on', 'off'])
})

test('a missing hyprctl or failed dispatch never throws', async () => {
  const set = createHyprlandIdleInhibitor(async () => { throw new Error('ENOENT') }, 1)
  await set(fakeWindow(), true)
  const refused = createHyprlandIdleInhibitor(async (args) => (args[0] === '-j' ? '[{"address":"0x1","pid":1,"title":"t"}]' : 'false'), 1)
  await refused(fakeWindow(), true)
})
