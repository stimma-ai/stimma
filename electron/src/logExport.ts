import { randomUUID } from 'node:crypto'
import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import { crc32, deflateRaw } from 'node:zlib'

const compress = promisify(deflateRaw)
const MAX_LOG_BYTES = 5 * 1024 * 1024
const LOG_NAMES = [
  'Stimma-shell.log',
  ...Array.from({ length: 4 }, (_, i) => `Stimma-shell.log.${i + 1}`),
  ...Array.from({ length: 20 }, (_, i) => `Stimma_log.${String(i).padStart(2, '0')}.txt`),
]

export function scrubLogExport(text: string, home = os.homedir()): string {
  // Match the feedback scrubber's secret assignments, including quoted JSON keys.
  text = text.replace(
    /\b(authorization)(["']?\s*[:=]\s*["']?)(?:(?:bearer|basic)\s+)?[^\s"',;]+/gi,
    '$1$2[redacted]',
  ).replace(
    /\b(api[_-]?key|(?:access[_-]|refresh[_-]|id[_-]|auth[_-])?token|(?:client[_-])?secret|password|passwd|pin)(["']?\s*[:=]\s*["']?)[^\s"',;&]+/gi,
    '$1$2[redacted]',
  ).replace(/\b(bearer)\s+[A-Za-z0-9._-]{16,}/gi, '$1 [redacted]')
    .replace(/\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b/g, '[redacted]')
    .replace(/\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,})\b/g, '[redacted]')
    .replace(/\b[A-Za-z0-9_+/=-]{32,}\b/g, '[redacted]')
  // Include escaped Windows paths (JSON), alternate separators, and other homes
  // that may have appeared in imported diagnostics, not just the current home.
  const homes = new Set([home, home.replaceAll('\\', '/'), home.replaceAll('\\', '\\\\')])
  for (const value of homes) {
    if (value) text = text.replace(new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), '~')
  }
  return text.replace(/[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n"'<>]+/gi, '~')
    .replace(/\/(?:home|Users)\/[^/\r\n"'<>]+/g, '~')
}

/** A small classic ZIP writer: fixed ASCII names, deflate, no ZIP64 needed. */
export async function exportLogs(
  destination: string,
  dataDir: string,
  version: string,
): Promise<void> {
  const logsDir = path.join(dataDir, 'Logs')
  const resolve = (filename: string) => process.platform === 'win32'
    ? path.resolve(filename).toLowerCase() : path.resolve(filename)
  if (LOG_NAMES.some((name) => resolve(path.join(logsDir, name)) === resolve(destination))) {
    throw new Error('Export would overwrite a log')
  }
  const temporary = destination + `.${randomUUID()}.tmp`
  const output = await fs.open(temporary, 'wx', 0o600)
  const central: Buffer[] = []
  let offset = 0
  try {
    const add = async (name: string, text: string) => {
      const data = Buffer.from(scrubLogExport(text), 'utf8')
      const compressed = await compress(data)
      const filename = Buffer.from(name)
      const header = Buffer.alloc(30)
      header.writeUInt32LE(0x04034b50, 0)
      header.writeUInt16LE(20, 4) // Version needed: ZIP 2.0.
      header.writeUInt16LE(8, 8) // Raw deflate.
      header.writeUInt16LE(0x21, 12) // 1980-01-01, the earliest DOS date.
      header.writeUInt32LE(crc32(data), 14)
      header.writeUInt32LE(compressed.length, 18)
      header.writeUInt32LE(data.length, 22)
      header.writeUInt16LE(filename.length, 26)
      const directory = Buffer.alloc(46)
      directory.writeUInt32LE(0x02014b50, 0)
      directory.writeUInt16LE(20, 4)
      header.copy(directory, 6, 4, 30)
      directory.writeUInt32LE(offset, 42)
      central.push(Buffer.concat([directory, filename]))
      const entry = Buffer.concat([header, filename, compressed])
      await output.writeFile(entry)
      offset += entry.length
    }
    for (const name of LOG_NAMES) {
      let input
      try {
        input = await fs.open(path.join(logsDir, name), 'r')
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue
        throw error
      }
      try {
        const { size } = await input.stat()
        const start = Math.max(0, size - MAX_LOG_BYTES)
        const buffer = Buffer.alloc(Math.min(size, MAX_LOG_BYTES))
        let length = 0
        while (length < buffer.length) {
          const { bytesRead } = await input.read(buffer, length, buffer.length - length, start + length)
          if (!bytesRead) break
          length += bytesRead
        }
        // Drop a partial first line so a cut-off secret's value cannot leak.
        let text = buffer.subarray(0, length).toString('utf8')
        if (start) text = text.includes('\n') ? text.slice(text.indexOf('\n') + 1) : ''
        await add(name, text)
      } finally {
        await input.close()
      }
    }
    await add('version.txt', `Version: ${version}\nPlatform: ${process.platform}\nArchitecture: ${process.arch}\nElectron: ${process.versions.electron ?? ''}\n`)
    const directory = Buffer.concat(central)
    const end = Buffer.alloc(22)
    end.writeUInt32LE(0x06054b50, 0)
    end.writeUInt16LE(central.length, 8)
    end.writeUInt16LE(central.length, 10)
    end.writeUInt32LE(directory.length, 12)
    end.writeUInt32LE(offset, 16)
    await output.writeFile(Buffer.concat([directory, end]))
    await output.close()
    await fs.rename(temporary, destination)
  } catch (error) {
    await output.close().catch(() => {})
    await fs.rm(temporary, { force: true }).catch(() => {})
    throw error
  }
}

export async function promptLogExport(
  dataDir: string,
  version: string,
  dialogs: {
    showSaveDialog: (options: { defaultPath: string }) => Promise<{ canceled: boolean; filePath?: string }>
    showErrorBox: (title: string, content: string) => void
  },
): Promise<void> {
  try {
    const result = await dialogs.showSaveDialog({ defaultPath: 'Stimma-logs.zip' })
    if (!result.canceled && result.filePath) await exportLogs(result.filePath, dataDir, version)
  } catch {
    dialogs.showErrorBox('Stimma', "Couldn't export logs.")
  }
}
