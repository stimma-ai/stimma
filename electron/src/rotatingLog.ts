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
  private pending: Buffer = Buffer.alloc(0)
  private droppingRecord = false

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
        // The bounded tail may start inside a secret value. Keep whole lines.
        const data = tail.subarray(0, offset)
        const newline = data.indexOf(10)
        await files.writeFile(filename + '.tmp', newline < 0 ? Buffer.alloc(0) : data.subarray(newline + 1), { mode: 0o600 })
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
    while (chunk.length) {
      const newline = chunk.indexOf(10)
      const length = newline < 0 ? chunk.length : newline + 1
      const part = chunk.subarray(0, length)
      if (!this.droppingRecord) {
        if (this.pending.length + length > this.maxBytes) {
          this.pending = Buffer.alloc(0)
          this.droppingRecord = true
        } else {
          this.pending = Buffer.concat([this.pending, part])
        }
      }
      if (newline >= 0) {
        if (!this.droppingRecord) await this.appendRecord(this.pending)
        this.pending = Buffer.alloc(0)
        this.droppingRecord = false
      }
      chunk = chunk.subarray(length)
    }
  }

  private async appendRecord(record: Buffer): Promise<void> {
    if (this.failed || !record.length) return
    if (await this.size(this.filename) + record.length > this.maxBytes) await this.rotate()
    if (!this.output) {
      this.output = fs.createWriteStream(this.filename, { flags: 'a', mode: 0o600 })
      this.output.on('error', (error) => this.fail(error))
    }
    await new Promise<void>((resolve, reject) => {
      this.output!.write(record, (error) => error ? reject(error) : resolve())
    })
  }

  override _final(callback: () => void): void {
    void this.appendRecord(this.pending).then(() => this.closeOutput())
      .catch((error) => this.fail(error)).then(() => callback())
  }
}
