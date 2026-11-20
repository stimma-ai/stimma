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

type HyprClient = { address: string; pid: number; title: string }
type Run = (args: string[]) => Promise<string>

export function onHyprland(env: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): boolean {
  return platform === 'linux' && !!env.HYPRLAND_INSTANCE_SIGNATURE
}

const runHyprctl: Run = (args) =>
  new Promise((resolve, reject) => {
    execFile('hyprctl', args, { timeout: 3000 }, (error, stdout) => (error ? reject(error) : resolve(String(stdout))))
  })

/**
 * This process's toplevel for the requesting window: the one whose title
 * matches, or, when the sender is our only visible window, our only client.
 * Ambiguous matches return null so another Stimma window is never marked.
 */
export function pickWindowAddress(clients: HyprClient[], pid: number, title: string, senderIsSole = false): string | null {
  const ours = clients.filter((c) => c.pid === pid)
  const candidates = senderIsSole && ours.length === 1 ? ours : ours.filter((c) => c.title === title)
  const only = candidates.length === 1 ? candidates[0] : null
  return only && /^0x[0-9a-f]+$/i.test(only.address) ? only.address : null
}

function idleInhibitScript(address: string, active: boolean): string {
  return `return tostring(hl.dispatch(hl.dsp.window.set_prop({window='address:${address}', prop='idle_inhibit', value='${active ? 1 : 0}'})).ok)`
}

type WindowState = { wanted: boolean; applied: boolean; address: string | null; chain: Promise<void> }

export function createHyprlandIdleInhibitor(
  run: Run = runHyprctl,
  pid = process.pid,
  visibleWindowCount: () => number = () => 1,
) {
  const states = new WeakMap<BrowserWindow, WindowState>()

  async function apply(win: BrowserWindow, state: WindowState): Promise<void> {
    if (state.wanted === state.applied || win.isDestroyed()) return
    // The value actually sent; `wanted` may change while the command runs, and
    // the queued follow-up call reconciles the difference.
    const target = state.wanted
    try {
      if (!state.address) {
        const senderIsSole = win.isVisible() && visibleWindowCount() === 1
        state.address = pickWindowAddress(JSON.parse(await run(['-j', 'clients'])), pid, win.getTitle(), senderIsSole)
      }
      if (!state.address) return
      const ok = (await run(['repl', idleInhibitScript(state.address, target)])).trim() === 'true'
      if (ok) state.applied = target
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
