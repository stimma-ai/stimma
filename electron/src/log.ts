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
    // Keep loopback URLs and scheme/path diagnostics; redact other authorities and credentials.
    .replace(/([a-z][a-z0-9+.-]*:\/\/)([^\s/?#"'<>]+)/gi, (value, scheme, authority) => {
      const host = /^(?:\[([^\]]+)\]|([^:@]+))(?::\d+)?$/.exec(authority)
      return host && isLoopbackHost(host[1] ?? host[2]) ? value : `${scheme}[redacted]`
    })
    .replace(/\[([a-f0-9:.]+(?:%[a-z0-9]+)?)\](?::\d{1,5})?/gi, scrubIP)
    .replace(/(?<![\w:])(?:[a-f0-9]{0,4}:){2,}(?:(?:\d{1,3}\.){3}\d{1,3}|[a-f0-9:]*)(?:%[a-z0-9]+)?(?![\w:])/gi, (value) => scrubIP(value, value))
    .replace(/(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?(?![\w.])/g, scrubIP)
    // Dotted hosts need an alphabetic final label. Preserve known source locations.
    .replace(/(?<![\w.-])(?:[a-z0-9_-]+\.)+[a-z]{2,}\.?(?::\d+)?(?![\w.-])/gi, (value) =>
      /\.(?:[cm]?[jt]sx?|vue|svelte|json|py|rb|rs|go|c|h|cc|cpp|hpp|cs|java|kt|swift|sh):\d+$/i.test(value) ? value : '[redacted]')
}

function isLoopbackHost(host: string): boolean {
  return host.toLowerCase() === 'localhost'
    || (isIP(host) === 4 && host.startsWith('127.'))
    || (isIP(host) === 6 && /^(?:0*:){2,7}0*1$/.test(host.split('%')[0]))
}

function scrubIP(value: string, host: string): string {
  return isIP(host) && !isLoopbackHost(host) ? '[redacted]' : value
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
