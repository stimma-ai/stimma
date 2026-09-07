import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { readPackagedMetadata, type AppIdentity } from './identity'
import { log } from './log'
import { parsePythonRuntimeArchive, selectPythonRuntimeArchive } from './pythonRuntimeName'

const LOCK_STALE_MS = 10 * 60 * 1000
const LOCK_WAIT_MS = 10 * 60 * 1000

function runtimeArchive(): { path: string; sha256: string } | null {
  if (process.platform !== 'win32') return null
  const metadata = readPackagedMetadata(path.join(process.resourcesPath, 'app.asar'))
  const selected = selectPythonRuntimeArchive(fs.readdirSync(process.resourcesPath), metadata.stimmaPythonRuntimeArchive)
  if (!selected) return null // Backward-compatible loose runtime.
  return { path: path.join(process.resourcesPath, selected.name), sha256: selected.sha256 }
}

// Only installer preparation calls this, after the selected runtime is ready.
// An interrupted uninstall can leave previous transport archives in resources.
// Extracted runtimes remain untouched: another sandbox may still be using them.
export async function removeObsoleteRuntimeArchives(): Promise<void> {
  const current = runtimeArchive()
  if (!current) return
  for (const name of await fs.promises.readdir(process.resourcesPath)) {
    const filename = path.join(process.resourcesPath, name)
    if (parsePythonRuntimeArchive(name) && filename !== current.path) {
      await fs.promises.unlink(filename)
      log.info('python-runtime', `Removed obsolete transport archive: ${name}`)
    }
  }
}

function runtimeBaseDir(identity: AppIdentity): string {
  const explicit = process.env.STIMMA_RUNTIME_DIR
  if (explicit) return explicit
  // The normal data layout is <bundle id>/<sandbox>. Keep the runtime beside
  // sandboxes so every sandbox shares one immutable dependency environment.
  return path.join(path.dirname(identity.dataDir), '.python-runtime')
}

async function sha256File(filename: string): Promise<string> {
  return await new Promise((resolve, reject) => {
    const hash = createHash('sha256')
    const stream = fs.createReadStream(filename)
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('error', reject)
    stream.on('end', () => resolve(hash.digest('hex')))
  })
}

async function isComplete(directory: string, sha256: string): Promise<boolean> {
  try {
    const marker = await fs.promises.readFile(path.join(directory, '.complete'), 'utf8')
    return marker.trim() === sha256 && fs.existsSync(path.join(directory, 'python.exe'))
  } catch {
    return false
  }
}

async function extractArchive(archive: string, destination: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn('tar.exe', ['-xf', archive, '-C', destination], {
      windowsHide: true,
      stdio: ['ignore', 'ignore', 'pipe'],
    })
    let stderr = ''
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`tar.exe failed with exit code ${code}: ${stderr.trim()}`))
    })
  })
}

async function acquireLock(lockPath: string, ready: () => Promise<boolean>): Promise<fs.promises.FileHandle | null> {
  const deadline = Date.now() + LOCK_WAIT_MS
  while (Date.now() < deadline) {
    if (await ready()) return null
    try {
      const handle = await fs.promises.open(lockPath, 'wx')
      await handle.writeFile(JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }))
      return handle
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code
      if (code !== 'EEXIST') throw error
      try {
        const stat = await fs.promises.stat(lockPath)
        if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
          await fs.promises.unlink(lockPath)
          continue
        }
      } catch (statError) {
        if ((statError as NodeJS.ErrnoException).code !== 'ENOENT') throw statError
      }
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  throw new Error('Timed out waiting for another Stimma process to prepare the Python runtime')
}

export async function preparePythonRuntime(identity: AppIdentity): Promise<string | null> {
  const archive = runtimeArchive()
  if (!archive) return null

  const base = runtimeBaseDir(identity)
  const destination = path.join(base, archive.sha256)
  await fs.promises.mkdir(base, { recursive: true })
  if (await isComplete(destination, archive.sha256)) return destination

  const lockPath = path.join(base, `${archive.sha256}.lock`)
  const lock = await acquireLock(lockPath, () => isComplete(destination, archive.sha256))
  if (!lock) return destination

  const temporary = path.join(base, `${archive.sha256}.tmp-${process.pid}-${Date.now()}`)
  const started = Date.now()
  try {
    if (await isComplete(destination, archive.sha256)) return destination
    const actualHash = await sha256File(archive.path)
    if (actualHash !== archive.sha256) {
      throw new Error(`Python runtime archive hash mismatch: expected ${archive.sha256}, got ${actualHash}`)
    }

    await fs.promises.rm(temporary, { recursive: true, force: true })
    await fs.promises.mkdir(temporary, { recursive: true })
    log.info('python-runtime', `Extracting ${path.basename(archive.path)} to ${destination}`)
    await extractArchive(archive.path, temporary)
    if (!fs.existsSync(path.join(temporary, 'python.exe'))) {
      throw new Error('Extracted Python runtime does not contain python.exe')
    }
    await fs.promises.writeFile(path.join(temporary, '.complete'), `${archive.sha256}\n`, 'utf8')
    await fs.promises.rm(destination, { recursive: true, force: true })
    await fs.promises.rename(temporary, destination)
    log.info('python-runtime', `Runtime ready in ${((Date.now() - started) / 1000).toFixed(2)}s`)
    return destination
  } finally {
    await fs.promises.rm(temporary, { recursive: true, force: true }).catch(() => {})
    await lock.close().catch(() => {})
    await fs.promises.unlink(lockPath).catch(() => {})
  }
}
