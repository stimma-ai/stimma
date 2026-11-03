/**
 * Minimal main-process logger. Writes to <dataDir>/Logs/Stimma-shell.log and
 * mirrors to stdout/stderr (dev CLI merges those into its combined view).
 */

import { RotatingLog } from './rotatingLog.ts'
import path from 'node:path'

let stream: RotatingLog | null = null

export function initLog(dataDir: string): void {
  stream = new RotatingLog(path.join(dataDir, 'Logs', 'Stimma-shell.log'))
}

function write(level: string, target: string, message: string): void {
  const line = `[${new Date().toISOString()}][${level}][${target}] ${message}`
  if (level === 'error' || level === 'warn') console.error(line)
  else console.log(line)
  stream?.write(line + '\n')
}

export const log = {
  info: (target: string, message: string) => write('info', target, message),
  warn: (target: string, message: string) => write('warn', target, message),
  error: (target: string, message: string) => write('error', target, message),
  debug: (target: string, message: string) => write('debug', target, message),
}
