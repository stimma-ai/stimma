const ARCHIVE_RE = /^stimma-python-runtime-([a-f0-9]{64})\.tar\.xz$/

export function parsePythonRuntimeArchive(name: string): string | null {
  return ARCHIVE_RE.exec(name)?.[1] ?? null
}
