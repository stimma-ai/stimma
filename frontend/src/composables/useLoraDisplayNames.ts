export interface LoraDisplayName {
  primary: string
  secondary: string
}

const GENERIC_ARTIFACT_STEM_PATTERNS: RegExp[] = [
  /^pytorch_lora_weights(?:[_-]\d+)?$/i,
  /^optimizer(?:[_-].*)?$/i,
  /^scheduler(?:[_-].*)?$/i,
  /^random_states?(?:[_-]\d+)?$/i,
  /^adapter_model(?:[_-].*)?$/i,
  /^training_args(?:[_-].*)?$/i,
  /^scaler(?:[_-].*)?$/i
]

const GENERIC_DIRECTORY_SEGMENTS = new Set([
  'loras',
  'lora',
  'models',
  'model',
  'checkpoints',
  'checkpoint',
  'output',
  'outputs',
  'weights'
])

function splitPath(path: string): string[] {
  return path.split('/').filter(Boolean)
}

function stripExtension(name: string): string {
  return name.replace(/\.[^/.]+$/i, '')
}

function humanize(segment: string): string {
  return segment.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
}

function formatLargeNumber(raw: string): string {
  const num = parseInt(raw, 10)
  if (!Number.isFinite(num)) return raw
  if (num >= 1_000_000) return `${num % 1_000_000 === 0 ? num / 1_000_000 : (num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${num % 1_000 === 0 ? num / 1_000 : (num / 1_000).toFixed(1)}k`
  return String(num)
}

function isCheckpointSegment(segment: string): boolean {
  return /^(checkpoint|ckpt|step|epoch)[-_]?\d+$/i.test(segment)
}

function isGenericArtifactStem(stem: string): boolean {
  return GENERIC_ARTIFACT_STEM_PATTERNS.some(pattern => pattern.test(stem))
}

function isInformativeSegment(segment: string): boolean {
  const lower = segment.toLowerCase()
  if (!lower || GENERIC_DIRECTORY_SEGMENTS.has(lower)) return false
  if (isCheckpointSegment(lower)) return false
  return /[a-z]/i.test(lower)
}

/**
 * Tokenize a model name like "Flux.2 klein 9b" into a set of banned tokens.
 * Generates all plausible variants that lora filenames might use:
 *   "Flux.2 klein 9b" → flux.2, flux2, flux, klein, 9b
 * Plus consecutive-pair smooshes:
 *   klein9b, flux2klein, klein9b, etc.
 */
function tokenizeModelName(modelName: string): string[] {
  // Split on whitespace first, keeping punctuation intact
  const rawWords = modelName.split(/\s+/).filter(Boolean).map(w => w.toLowerCase())
  const tokens = new Set<string>()

  for (const word of rawWords) {
    tokens.add(word)                          // "flux.2" as-is
    const stripped = word.replace(/[._-]/g, '') // "flux2"
    if (stripped.length >= 2) tokens.add(stripped)
    // sub-parts: "flux.2" → "flux", "2"
    for (const part of word.split(/[._-]+/)) {
      if (part.length >= 2) tokens.add(part)
    }
  }

  // Consecutive-pair smooshes: ["klein","9b"] → "klein9b"
  for (let i = 0; i < rawWords.length - 1; i++) {
    const a = rawWords[i].replace(/[._-]/g, '')
    const b = rawWords[i + 1].replace(/[._-]/g, '')
    if (a && b) tokens.add(a + b)
  }

  return Array.from(tokens)
}

/** Check if a lora token is redundant given the model name tokens (fuzzy substring match) */
function isModelRedundantToken(token: string, modelTokens: string[]): boolean {
  const lower = token.toLowerCase()
  for (const mt of modelTokens) {
    if (lower.includes(mt) || mt.includes(lower)) return true
  }
  return false
}

function isTrainingSuffixToken(token: string): boolean {
  return (
    /^r(?:ank)?[-_]?(\d+)$/i.test(token) ||
    /^(adamw|adamw8bit|adafactor|lion|sgd|optimizer|weighted|bf16|fp16|fp8|lora)$/i.test(token) ||
    /^\(?\d+\)?$/.test(token) ||
    /^\d{4,}$/.test(token)
  )
}

function isVersionToken(token: string): boolean {
  return /^v\d+(?:\.\d+)?$/i.test(token)
}

function getCleanPrimaryStem(stem: string, modelTokens: string[]): string {
  const normalized = stem
    .replace(/\((\d+)\)\s*$/g, '')
    .replace(/[.]+/g, '_')
  const tokens = normalized.split(/[\s_-]+/).filter(Boolean)

  if (tokens.length === 0) return stem

  // Filter out model-redundant tokens and version tokens from anywhere
  const filtered = tokens.filter(t =>
    !isModelRedundantToken(t, modelTokens) && !isVersionToken(t)
  )

  // If everything was filtered, fall back to original tokens
  if (filtered.length === 0) return tokens.join(' ')

  let end = filtered.length
  while (end > 1 && isTrainingSuffixToken(filtered[end - 1])) {
    end -= 1
  }

  return filtered.slice(0, end).join(' ')
}

function extractSecondaryChips(path: string, modelTokens: string[]): string[] {
  const chips: string[] = []
  const seen = new Set<string>()
  const segments = splitPath(stripExtension(path))

  for (const segment of segments) {
    const checkpointMatch = segment.match(/^(checkpoint|ckpt|step|epoch)[-_]?(\d+)$/i)
    if (checkpointMatch) {
      const tag = checkpointMatch[1].toLowerCase()
      const value = formatLargeNumber(checkpointMatch[2]).toLowerCase()
      const chip = `${tag}-${value}`
      if (!seen.has(chip)) {
        seen.add(chip)
        chips.push(chip)
      }
      continue
    }

    const versionMatches = Array.from(segment.matchAll(/(?:^|[_-])(v\d+(?:\.\d+)?)(?=$|[_-])/gi))
    for (const match of versionMatches) {
      const chip = match[1].toLowerCase()
      if (!seen.has(chip)) {
        seen.add(chip)
        chips.push(chip)
      }
    }

    const normalizedSegment = segment.replace(/[.]+/g, '_')

    const rankMatches = Array.from(
      normalizedSegment.matchAll(/(?:^|[_-])(r(?:ank)?[-_]?\d+)(?=$|[_-])/gi)
    )
    for (const match of rankMatches) {
      const chip = match[1].replace(/[-_]/g, '').toLowerCase()
      if (!seen.has(chip)) {
        seen.add(chip)
        chips.push(chip)
      }
    }

    const rawStepMatches = Array.from(
      normalizedSegment.matchAll(/(?:^|[_-])(\d{4,})(?=$|[_-])/g)
    )
    for (const match of rawStepMatches) {
      if (isModelRedundantToken(match[1], modelTokens)) continue
      const chip = `step-${formatLargeNumber(match[1]).toLowerCase()}`
      if (!seen.has(chip)) {
        seen.add(chip)
        chips.push(chip)
      }
    }
  }

  return chips
}

function getPrimaryFromPath(path: string, modelTokens: string[]): string {
  const segments = splitPath(path)
  const filename = segments[segments.length - 1] || path
  const stem = stripExtension(filename)
  const cleanStem = getCleanPrimaryStem(stem, modelTokens)

  if (!isGenericArtifactStem(stem) && /[a-z]/i.test(cleanStem)) {
    return humanize(cleanStem)
  }

  for (let i = segments.length - 2; i >= 0; i--) {
    const segment = segments[i]
    if (isInformativeSegment(segment)) {
      const cleaned = getCleanPrimaryStem(segment, modelTokens)
      if (/[a-z]/i.test(cleaned)) return humanize(cleaned)
    }
  }

  return humanize(stem || filename)
}

export function computeDisplayNames(paths: string[], modelName?: string): Record<string, LoraDisplayName> {
  if (paths.length === 0) return {}

  const modelTokens = modelName ? tokenizeModelName(modelName) : []

  const baseEntries = paths.map(path => ({
    path,
    primary: getPrimaryFromPath(path, modelTokens),
    secondary: extractSecondaryChips(path, modelTokens).join(' ')
  }))

  // Only disambiguate when both primary and secondary collide.
  const groupedByDisplay = new Map<string, typeof baseEntries>()
  for (const entry of baseEntries) {
    const key = `${entry.primary.toLowerCase()}||${entry.secondary.toLowerCase()}`
    const group = groupedByDisplay.get(key) || []
    group.push(entry)
    groupedByDisplay.set(key, group)
  }

  const result: Record<string, LoraDisplayName> = {}
  for (const [key, group] of groupedByDisplay) {
    if (group.length === 1) {
      const only = group[0]
      result[only.path] = { primary: only.primary, secondary: only.secondary }
      continue
    }

    const [primaryKey] = key.split('||')
    const groupDifferentiators = new Map<string, string>()
    const uniqueDifferentiators = new Set<string>()

    for (const entry of group) {
      const segments = splitPath(entry.path)
      let differentiator = ''
      for (let i = segments.length - 2; i >= 0; i--) {
        const segment = segments[i]
        if (!isInformativeSegment(segment)) continue
        const candidate = humanize(segment)
        if (candidate.toLowerCase() !== primaryKey) {
          differentiator = candidate
          break
        }
      }

      groupDifferentiators.set(entry.path, differentiator)
      if (differentiator) {
        uniqueDifferentiators.add(differentiator.toLowerCase())
      }
    }

    const shouldAppendDifferentiator = uniqueDifferentiators.size > 1

    for (const entry of group) {
      const differentiator = groupDifferentiators.get(entry.path) || ''
      result[entry.path] = {
        primary: shouldAppendDifferentiator && differentiator
          ? `${entry.primary} (${differentiator})`
          : entry.primary,
        secondary: entry.secondary
      }
    }
  }

  return result
}

/** Get raw display name: filename without extension, underscores/hyphens to spaces */
export function getRawDisplayName(path: string): string {
  const filename = path.split('/').pop() || path
  return filename.replace(/\.safetensors$/i, '')
}

/** Get raw filename with extension intact */
export function getRawFileName(path: string): string {
  return path.split('/').pop() || path
}

/** Get the directory portion of a lora path (everything before the filename) */
export function getDirectoryPath(path: string): string {
  const lastSlash = path.lastIndexOf('/')
  if (lastSlash === -1) return ''
  return path.substring(0, lastSlash)
}
