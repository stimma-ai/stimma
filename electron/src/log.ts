/**
 * Minimal main-process logger. Writes to <dataDir>/Logs/Stimma-shell.log and
 * mirrors to stdout/stderr (dev CLI merges those into its combined view).
 */

import { RotatingLog } from './rotatingLog.ts'
import path from 'node:path'
import { isIP } from 'node:net'

let stream: RotatingLog | null = null

export function initLog(dataDir: string): void {
  stream = new RotatingLog(path.join(dataDir, 'Logs', 'Stimma-shell.log'))
}

/** All shell writers pass here, including renderer/updater logs and errors. */
export function scrubNetworkDetails(message: string): string {
  return message
    // Keep the scheme/path for diagnosis, never a URL's authority (or credentials).
    .replace(/([a-z][a-z0-9+.-]*:\/\/)[^\s/?#"'<>]+/gi, '$1[redacted]')
    // Socket endpoints, including bare DNS names. File/line references are not hosts.
    .replace(/(?<![\w.:-])(?!(?:[\w.-]+\.)?(?:js|mjs|cjs|ts|tsx|json|py):)(?:[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)*|(?:\d{1,3}\.){3}\d{1,3}|\[[a-f0-9:]+\]):\d{1,5}(?![\w.])/gi, '[redacted]')
    .replace(/\b(?:getaddrinfo\s+)?(?:ENOTFOUND|EAI_AGAIN)\s+[^\s"'<>]+/g, '[redacted]')
    // Bare LAN/tailnet addresses. Require address shapes, not arbitrary numbers.
    .replace(/(?<![\w.])(?:(?:10|127)(?:\.\d{1,3}){3}|(?:169\.254|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))(?:\.\d{1,3}){2})(?![\w.])/g, '[redacted]')
    .replace(/(?<![\w:])(?:[a-f0-9]{0,4}:){2,}[a-f0-9:]*(?:%[a-z0-9]+)?(?![\w:])/gi, (value) => isIP(value) === 6 ? '[redacted]' : value)
    .replace(/(?<![\w.-])(?:[a-z0-9_-]+\.)+(?:local|lan|internal|home|ts\.net)\b/gi, '[redacted]')
}

function write(level: string, target: string, message: string): void {
  const line = `[${new Date().toISOString()}][${level}][${target}] ${scrubNetworkDetails(message)}`
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
