/**
 * stimma-native helper client.
 *
 * One helper process per app instance, spawned lazily on first use and
 * restarted on the next request if it crashes. Speaks the JSON-lines
 * protocol (see native/stimma-native/src/protocol.rs): requests get
 * id-matched responses; voice streams arrive as event frames tied to the
 * originating request id and are relayed to the owning window.
 */

import { spawn, ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import readline from 'node:readline'
import type { AppIdentity } from './identity'
import { log } from './log'

interface Pending {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
}

let child: ChildProcess | null = null
let nextId = 1
const pending = new Map<number, Pending>()
const eventListeners = new Map<number, (payload: unknown) => void>()
let identity: AppIdentity | null = null

export function initHelper(appIdentity: AppIdentity): void {
  identity = appIdentity
}

function helperBinaryPath(): string {
  if (identity?.dev) {
    // Dev: use the cargo build output (debug, then release).
    const nativeTarget = path.join(__dirname, '..', '..', 'native', 'stimma-native', 'target')
    for (const profile of ['debug', 'release']) {
      const candidate = path.join(nativeTarget, profile, 'stimma-native')
      if (fs.existsSync(candidate)) return candidate
      if (fs.existsSync(candidate + '.exe')) return candidate + '.exe'
    }
    throw new Error('stimma-native not built — run `cargo build` in native/stimma-native')
  }
  const base = path.join(process.resourcesPath, 'stimma-native')
  return fs.existsSync(base) ? base : base + '.exe'
}

function ensureHelper(): ChildProcess {
  if (child && child.exitCode === null) return child
  if (!identity) throw new Error('Helper not initialized')

  const binary = helperBinaryPath()
  log.info('helper', `Spawning stimma-native from: ${binary}`)
  const proc = spawn(binary, ['--cache-dir', identity.cacheDir], {
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  })
  child = proc

  const rl = readline.createInterface({ input: proc.stdout! })
  rl.on('line', (line) => {
    let frame: any
    try {
      frame = JSON.parse(line)
    } catch {
      log.error('helper', `non-JSON frame: ${line.slice(0, 200)}`)
      return
    }
    if (typeof frame.event === 'string') {
      const listener = eventListeners.get(frame.id)
      listener?.(frame.payload)
      return
    }
    const entry = pending.get(frame.id)
    if (!entry) return
    pending.delete(frame.id)
    if (typeof frame.error === 'string') entry.reject(new Error(frame.error))
    else entry.resolve(frame.result)
  })

  const errRl = readline.createInterface({ input: proc.stderr! })
  errRl.on('line', (line) => log.info('helper', line))

  proc.on('exit', (code, signal) => {
    log.warn('helper', `stimma-native exited (code=${code}, signal=${signal})`)
    if (child === proc) child = null
    for (const [, entry] of pending) {
      entry.reject(new Error('stimma-native helper exited'))
    }
    pending.clear()
    eventListeners.clear()
  })

  return proc
}

export interface HelperCall {
  id: number
  result: Promise<unknown>
}

/**
 * Send one request. `streamEnds` controls event-listener lifetime:
 * 'with-response' (download streams end when the request resolves) or
 * 'explicit' (voice_start's transcript stream outlives its response; remove
 * via removeEventListener when the session ends).
 */
export function helperCall(
  method: string,
  params?: unknown,
  onEvent?: (payload: unknown) => void,
  streamEnds: 'with-response' | 'explicit' = 'with-response',
): HelperCall {
  const proc = ensureHelper()
  const id = nextId++
  if (onEvent) eventListeners.set(id, onEvent)

  const result = new Promise((resolve, reject) => {
    pending.set(id, {
      resolve: (value) => {
        if (onEvent && streamEnds === 'with-response') eventListeners.delete(id)
        resolve(value)
      },
      reject: (error) => {
        if (onEvent) eventListeners.delete(id)
        reject(error)
      },
    })
    proc.stdin!.write(JSON.stringify({ id, method, params: params ?? {} }) + '\n')
  })
  return { id, result }
}

export function helperRequest(
  method: string,
  params?: unknown,
  onEvent?: (payload: unknown) => void,
): Promise<unknown> {
  return helperCall(method, params, onEvent).result
}

export function removeEventListener(id: number): void {
  eventListeners.delete(id)
}

export function shutdownHelper(): void {
  if (child && child.exitCode === null) {
    child.stdin?.end() // EOF → helper cancels capture and exits.
  }
  child = null
}
