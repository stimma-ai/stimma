import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import type { BrowserWindow, PowerMonitor } from 'electron'
import { installWindowPrivacyLifecycle } from '../src/windowPrivacy.ts'

test('system sleep/lock covers a still-focused window, and return respects its visibility', () => {
  const win = new EventEmitter()
  const power = new EventEmitter()
  const state = { focused: true, visible: true, minimized: false, destroyed: false }
  const signals: [string, boolean][] = []
  Object.assign(win, {
    isFocused: () => state.focused,
    isVisible: () => state.visible,
    isMinimized: () => state.minimized,
    isDestroyed: () => state.destroyed,
    webContents: { send: (channel: string, active: boolean) => signals.push([channel, active]) },
  })
  const publish = installWindowPrivacyLifecycle(win as BrowserWindow, power as PowerMonitor)
  publish()
  power.emit('suspend')
  power.emit('resume')
  power.emit('lock-screen')
  state.minimized = true
  power.emit('unlock-screen')
  state.minimized = false
  state.focused = false
  power.emit('resume')
  state.focused = true
  win.emit('focus')
  win.emit('hide')
  assert.deepEqual(signals.map(s => s[1]), [true, false, true, false, false, false, true, false])
  assert.ok(signals.every(s => s[0] === 'stimma:app-active'))

  state.destroyed = true
  win.emit('closed')
  for (const event of ['suspend', 'resume', 'lock-screen', 'unlock-screen']) {
    assert.equal(power.listenerCount(event), 0, 'closed windows must release global listeners')
    power.emit(event)
  }
  publish()
  assert.equal(signals.length, 8, 'no IPC to a destroyed renderer')
})
