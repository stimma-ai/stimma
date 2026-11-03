import type { ChildProcess } from 'node:child_process'
import readline from 'node:readline'

const DIAGNOSTIC_BYTES = 64 * 1024
const CRASH_MARKER = '[watchdog] Backend crashed:'

export function parseBackendPort(line: string): number | null {
  const idx = line.indexOf('STIMMA_BACKEND_PORT=')
  if (idx === -1) return null
  const match = line.slice(idx + 'STIMMA_BACKEND_PORT='.length).match(/^\d+/)
  if (!match) return null
  const port = Number.parseInt(match[0], 10)
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : null
}

/** Console output stays live, but only failure diagnostics enter the shell log. */
export function observeBackendOutput(
  child: ChildProcess,
  callbacks: {
    port: (port: number) => void
    output: (chunk: Buffer, stderr: boolean) => void
    diagnostic: (text: string) => void
  },
): () => void {
  let tail: Buffer = Buffer.alloc(0)
  let ready = false
  const saveTail = () => {
    if (tail.length) callbacks.diagnostic(tail.toString('utf8'))
    tail = Buffer.alloc(0)
  }
  for (const [stream, stderr] of [[child.stdout!, false], [child.stderr!, true]] as const) {
    stream.on('data', (chunk: Buffer) => {
      tail = Buffer.concat([tail, chunk.subarray(-DIAGNOSTIC_BYTES)]).subarray(-DIAGNOSTIC_BYTES)
      callbacks.output(chunk, stderr)
    })
    readline.createInterface({ input: stream }).on('line', (line) => {
      const port = parseBackendPort(line)
      if (port !== null) {
        ready = true
        callbacks.port(port)
      }
      if (stderr && line.startsWith(CRASH_MARKER)) {
        ready = false
        saveTail()
      }
    })
  }
  child.on('error', (error) => {
    saveTail()
    callbacks.diagnostic(`Watchdog error: ${error.message}`)
  })
  // 'close' follows stdio drainage; 'exit' can lose the final traceback.
  child.on('close', (code, signal) => {
    if (code !== 0 || signal || !ready) saveTail()
  })
  return saveTail
}
