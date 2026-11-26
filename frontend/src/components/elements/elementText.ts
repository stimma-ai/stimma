// Small text helpers shared by the element surfaces.

const BLOCK_START = /^\s*([-*>#]|\d+\.)\s/

/**
 * The instructions as a page shows them: the page already names the element,
 * so the file's own leading "# Name" heading goes, and hard-wrapped lines
 * rejoin their paragraph or list item so text reflows.
 */
export function elementInstructionsMarkdown(text: string): string {
  const out: string[] = []
  let fenced = false
  for (const line of (text || '').replace(/^\s*#\s+[^\n]*\n+/, '').split('\n')) {
    if (/^\s*```/.test(line)) fenced = !fenced
    const prev = out[out.length - 1]
    const joinable = !fenced && !/^\s*```/.test(line) && prev !== undefined && prev.trim() !== ''
      && line.trim() !== '' && !BLOCK_START.test(line) && !/^\s*#/.test(prev) && !/^\s*```/.test(prev)
    if (joinable) out[out.length - 1] = `${prev} ${line.trim()}`
    else out.push(line)
  }
  return out.join('\n')
}

/** "flux-3-klein" → "Flux 3 Klein" for "For …" lines. */
export function familyLabel(family: string | null | undefined): string {
  return (family || '')
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

const VIDEO_FORMATS = new Set(['mp4', 'webm', 'mov', 'mkv', 'm4v', 'avi'])
export function isVideoFormat(format: string | null | undefined): boolean {
  return VIDEO_FORMATS.has((format || '').toLowerCase())
}
