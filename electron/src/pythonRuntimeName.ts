const ARCHIVE_RE = /^stimma-python-runtime-([a-f0-9]{64})\.tar\.xz$/

export function parsePythonRuntimeArchive(name: string): string | null {
  return ARCHIVE_RE.exec(name)?.[1] ?? null
}

export function selectPythonRuntimeArchive(names: string[], expected?: string): { name: string; sha256: string } | null {
  if (expected !== undefined) {
    const sha256 = parsePythonRuntimeArchive(expected)
    if (!sha256) throw new Error('Invalid packaged Python runtime archive name')
    if (!names.includes(expected)) throw new Error(`Packaged Python runtime archive is missing: ${expected}`)
    return { name: expected, sha256 }
  }
  const matches = names.flatMap(name => {
    const sha256 = parsePythonRuntimeArchive(name)
    return sha256 ? [{ name, sha256 }] : []
  })
  if (matches.length > 1) throw new Error(`Expected one Python runtime archive, found ${matches.length}`)
  return matches[0] ?? null
}
