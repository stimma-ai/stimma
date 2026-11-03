import fs from 'node:fs'
import { promises as files } from 'node:fs'
import path from 'node:path'
import { Writable } from 'node:stream'
import { finished } from 'node:stream/promises'

export const SHELL_LOG_BYTES = 5 * 1024 * 1024
export const SHELL_LOG_FILES = 5 // Current file plus four backups.

/** Serialized, asynchronous rotation, including recovery of an old unbounded log. */
export class RotatingLog extends Writable {
  private output: fs.WriteStream | null = null
  private failed = false

  private filename: string
  private maxBytes: number
  private fileCount: number

  constructor(filename: string, maxBytes = SHELL_LOG_BYTES, fileCount = SHELL_LOG_FILES) {
    super()
    this.filename = filename
    this.maxBytes = maxBytes
    this.fileCount = fileCount
  }

  private fail(error: unknown): void {
    if (this.failed) return
    this.failed = true
    this.output?.destroy()
    console.error('[log] Shell log unavailable:', error)
  }

  override _construct(callback: (error?: Error | null) => void): void {
    void this.prepare().catch((error) => this.fail(error)).then(() => callback())
  }

  private async prepare(): Promise<void> {
    await files.mkdir(path.dirname(this.filename), { recursive: true })
    // Read only a bounded tail, even if an older install left a multi-GB log.
    for (let index = 0; index < this.fileCount; index++) {
      const filename = index ? `${this.filename}.${index}` : this.filename
      const size = await this.size(filename)
      if (size <= this.maxBytes) continue
      const input = await files.open(filename, 'r')
      const tail = Buffer.alloc(this.maxBytes)
      try {
        let offset = 0
        while (offset < tail.length) {
          const { bytesRead } = await input.read(tail, offset, tail.length - offset, size - tail.length + offset)
          if (!bytesRead) break
          offset += bytesRead
        }
        await files.writeFile(filename + '.tmp', tail.subarray(0, offset), { mode: 0o600 })
      } finally {
        await input.close()
      }
      await files.rename(filename + '.tmp', filename)
    }
    if (await this.size(this.filename) >= this.maxBytes) await this.rotate()
  }

  private async size(filename: string): Promise<number> {
    try {
      return (await files.stat(filename)).size
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return 0
      throw error
    }
  }

  private async closeOutput(): Promise<void> {
    if (!this.output) return
    const output = this.output
    this.output = null
    output.end()
    await finished(output)
  }

  private async rotate(): Promise<void> {
    // Close before renaming: Windows cannot rename an open log file.
    await this.closeOutput()
    await files.rm(`${this.filename}.${this.fileCount - 1}`, { force: true })
    for (let index = this.fileCount - 2; index >= 0; index--) {
      const source = index ? `${this.filename}.${index}` : this.filename
      try {
        await files.rename(source, `${this.filename}.${index + 1}`)
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
      }
    }
  }

  override _write(chunk: Buffer, _encoding: BufferEncoding, callback: () => void): void {
    void this.append(chunk).catch((error) => this.fail(error)).then(() => callback())
  }

  private async append(chunk: Buffer): Promise<void> {
    if (this.failed) return
    let size = await this.size(this.filename)
    while (chunk.length) {
      if (size >= this.maxBytes) {
        await this.rotate()
        size = 0
      }
      if (!this.output) {
        this.output = fs.createWriteStream(this.filename, { flags: 'a', mode: 0o600 })
        this.output.on('error', (error) => this.fail(error))
      }
      const part = chunk.subarray(0, this.maxBytes - size)
      await new Promise<void>((resolve, reject) => {
        this.output!.write(part, (error) => error ? reject(error) : resolve())
      })
      size += part.length
      chunk = chunk.subarray(part.length)
    }
  }

  override _final(callback: () => void): void {
    void this.closeOutput().catch((error) => this.fail(error)).then(() => callback())
  }
}
