/**
 * Keep the screen awake for one window on Hyprland.
 *
 * Chromium's screen wake lock only reaches the GNOME/freedesktop screensaver
 * services on D-Bus. Hyprland setups usually have neither, so the slideshow's
 * wake lock does nothing there. Hyprland does let a client set its own
 * window's idle_inhibit property, which its idle tooling honors. This module
 * does exactly that for the requesting window and nothing else: it is inert
 * off Hyprland, touches no config and no other windows, and fails silently.
 * Hyprland drops the property with the window, so a crash cannot leave the
 * screen stuck awake.
 */

import { execFile } from 'node:child_process'
import type { BrowserWindow } from 'electron'

type HyprClient = { address: string; pid: number; title: string; focusHistoryID: number }
type Run = (args: string[]) => Promise<string>

export function onHyprland(env: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): boolean {
  return platform === 'linux' && !!env.HYPRLAND_INSTANCE_SIGNATURE
}

const runHyprctl: Run = (args) =>
  new Promise((resolve, reject) => {
    execFile('hyprctl', args, { timeout: 3000 }, (error, stdout) => (error ? reject(error) : resolve(String(stdout))))
  })

/** This process's toplevel for `title`; with duplicates, the most recently focused. */
export function pickWindowAddress(clients: HyprClient[], pid: number, title: string): string | null {
  const ours = clients.filter((c) => c.pid === pid)
  const candidates = ours.length > 1 ? ours.filter((c) => c.title === title) : ours
  const best = candidates.sort((a, b) => a.focusHistoryID - b.focusHistoryID)[0]
  return best && /^0x[0-9a-f]+$/i.test(best.address) ? best.address : null
}

export function idleInhibitScript(address: string, active: boolean): string {
  return `return tostring(hl.dispatch(hl.dsp.window.set_prop({window='address:${address}', prop='idle_inhibit', value='${active ? 1 : 0}'})).ok)`
}

type WindowState = { wanted: boolean; applied: boolean; address: string | null; chain: Promise<void> }

export function createHyprlandIdleInhibitor(run: Run = runHyprctl, pid = process.pid) {
  const states = new WeakMap<BrowserWindow, WindowState>()

  async function apply(win: BrowserWindow, state: WindowState): Promise<void> {
    if (state.wanted === state.applied || win.isDestroyed()) return
    try {
      if (!state.address) {
        state.address = pickWindowAddress(JSON.parse(await run(['-j', 'clients'])), pid, win.getTitle())
      }
      if (!state.address) return
      const ok = (await run(['repl', idleInhibitScript(state.address, state.wanted)])).trim() === 'true'
      if (ok) state.applied = state.wanted
      else state.address = null // stale address or unsupported Hyprland; retry lookup next time
    } catch {
      state.address = null
    }
  }

  return function setKeepScreenAwake(win: BrowserWindow, active: boolean): Promise<void> {
    let state = states.get(win)
    if (!state) {
      const fresh: WindowState = { wanted: false, applied: false, address: null, chain: Promise.resolve() }
      state = fresh
      states.set(win, fresh)
      // A reload or renderer crash never sends the matching "off".
      const clear = () => void setKeepScreenAwake(win, false)
      win.webContents.on('did-navigate', clear)
      win.webContents.on('render-process-gone', clear)
    }
    state.wanted = active
    const current = state
    current.chain = current.chain.then(() => apply(win, current))
    return current.chain
  }
}
