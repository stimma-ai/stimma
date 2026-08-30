// Tier C packaged-app smoke: launch the real built .app (electron/out) in an
// isolated sandbox and prove the full stack — app → watchdog → backend →
// renderer — comes up, then quit and verify no orphans.
//
// The packaged app ignores debugger flags, so this drives it as a plain
// process and asserts through the shell log (which carries forwarded renderer
// console output via the console bridge) plus the OS process table.
//
// Run: node electron/tests/packaged-smoke.mjs [path-to-app-binary]

import { execSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))))
const defaultBinary = path.join(
  repoRoot, 'electron', 'out', 'mac-arm64', 'Stimma.app', 'Contents', 'MacOS', 'Stimma',
)
const binary = process.argv[2] || defaultBinary
if (!fs.existsSync(binary)) {
  console.error(`Packaged app binary not found: ${binary}`)
  console.error('Build first: tools/stimma app build')
  process.exit(1)
}

let failed = false
const check = (label, condition) => {
  if (condition) console.log(`ok - ${label}`)
  else {
    failed = true
    console.error(`FAIL - ${label}`)
  }
}

const sandboxDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stimma-packaged-smoke-'))
const dataDir = path.join(sandboxDir, 'data')
const cacheDir = path.join(sandboxDir, 'cache')
const shellLog = path.join(dataDir, 'Logs', 'Stimma-shell.log')

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
delete env.STIMMA_DEV
env.STIMMA_SANDBOX = 'packaged-smoke'
env.STIMMA_DATA_DIR = dataDir
env.STIMMA_CACHE_DIR = cacheDir

const appBundleForCount = path.resolve(binary, '..', '..', '..')
const pycBefore = Number(
  execSync(`find "${appBundleForCount}" -name "*.pyc" | wc -l`, { encoding: 'utf8' }).trim(),
)

const child = spawn(binary, [], { env, stdio: ['ignore', 'ignore', 'ignore'] })
const appPid = child.pid
console.log(`launched packaged app (pid ${appPid})`)

const readLog = () => (fs.existsSync(shellLog) ? fs.readFileSync(shellLog, 'utf8') : '')

const waitForLog = async (needle, timeoutMs) => {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (readLog().includes(needle)) return true
    if (child.exitCode !== null) return false
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

const descendants = (pid) => {
  try {
    const table = execSync('ps -axo pid=,ppid=', { encoding: 'utf8' })
      .trim().split('\n').map((l) => l.trim().split(/\s+/).map(Number))
    const children = new Map()
    for (const [p, pp] of table) {
      if (!children.has(pp)) children.set(pp, [])
      children.get(pp).push(p)
    }
    const out = []
    const walk = (n) => {
      for (const c of children.get(n) ?? []) {
        out.push(c)
        walk(c)
      }
    }
    walk(pid)
    return out
  } catch {
    return []
  }
}

let treePids = []
try {
  check('shell starts and creates windows', await waitForLog('Windows restored', 30000))

  check('watchdog spawned', await waitForLog('Watchdog spawned with pid', 15000))

  const gotPort = await waitForLog('Detected port:', 120000)
  check('backend reported its port to the shell', gotPort)
  const portMatch = readLog().match(/Detected port: (\d+)/)
  const port = portMatch ? Number(portMatch[1]) : 0

  // The renderer console is forwarded into the shell log; a 200 health check
  // proves renderer → app://stimma origin → CORS → backend end to end.
  check(
    'renderer health check against the backend returned 200',
    await waitForLog('Health check response: 200', 120000),
  )

  // Direct backend probe from outside for good measure.
  let health = 0
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/`)
    health = resp.status
  } catch {}
  check(`backend reachable from outside (status ${health})`, health === 200)

  treePids = [appPid, ...descendants(appPid)]
  const cmds = treePids
    .map((p) => {
      try {
        return execSync(`ps -o command= -p ${p}`, { encoding: 'utf8' }).trim()
      } catch {
        return ''
      }
    })
    .filter(Boolean)
  check(
    `process tree includes watchdog (${treePids.length} processes)`,
    cmds.some((c) => c.includes('stimma-watchdog')),
  )
  check('process tree includes python backend', cmds.some((c) => c.includes('python')))

  // Bundle must not be mutated by first launch (signature-seal invariant):
  // no NEW .pyc files may appear inside the app bundle (some ship pre-built
  // from pip install at packaging time).
  const appBundle = path.resolve(binary, '..', '..', '..')
  const countPyc = () => {
    try {
      return Number(
        execSync(`find "${appBundle}" -name "*.pyc" | wc -l`, { encoding: 'utf8' }).trim(),
      )
    } catch {
      return -1
    }
  }
  const pycAfter = countPyc()
  check(
    `no new .pyc written into the app bundle (before ${pycBefore}, after ${pycAfter})`,
    pycAfter === pycBefore && pycAfter >= 0,
  )
} finally {
  // Genuine quit (SIGTERM = Cmd-Q equivalent at the process level).
  child.kill('SIGTERM')
  await new Promise((resolve) => {
    child.on('exit', resolve)
    setTimeout(resolve, 10000)
  })
}

// Give the watchdog a moment to notice parent death and reap the backend.
await new Promise((r) => setTimeout(r, 5000))
const survivors = treePids.filter((p) => {
  try {
    process.kill(p, 0)
    return true
  } catch {
    return false
  }
})
check(
  `clean quit leaves no orphan processes (survivors: ${survivors.join(',') || 'none'})`,
  survivors.length === 0,
)

if (process.env.STIMMA_SMOKE_KEEP_SANDBOX) console.log(`sandbox kept: ${sandboxDir}`)
else fs.rmSync(sandboxDir, { recursive: true, force: true })

if (failed) process.exit(1)
console.log('packaged smoke: all checks passed')
