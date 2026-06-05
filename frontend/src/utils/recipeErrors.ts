export interface RecipeErrorInfo {
  category: string | null
  title: string
  message: string
  raw: string
}

const CATEGORY_LABELS: Record<string, string> = {
  tool_error: 'Tool error',
  code_error: 'Code error',
  llm_error: 'LLM error',
  transient: 'Temporary error',
  resource: 'Resource error',
  tool_unavailable: 'Tool unavailable',
}

export function parseRecipeError(rawError: unknown): RecipeErrorInfo | null {
  if (rawError == null) return null
  const raw = String(rawError).trim()
  if (!raw) return null

  const match = raw.match(/^\[([^\]]+)\]\s*(.*)$/s)
  const category = match ? match[1].trim() : null
  const message = (match ? match[2] : raw).trim() || raw
  return {
    category,
    title: titleForError(category, message),
    message: userMessageForError(category, message),
    raw,
  }
}

export function errorSummary(rawError: unknown): string {
  const parsed = parseRecipeError(rawError)
  return parsed?.message || ''
}

function titleForError(category: string | null, message: string): string {
  if (category && CATEGORY_LABELS[category]) return CATEGORY_LABELS[category]
  if (/is not defined|ReferenceError/i.test(message)) return 'Provider bug'
  if (/safety|content filter|moderation|blocked/i.test(message)) return 'Blocked by safety filter'
  if (/quota|credits|balance|limit/i.test(message)) return 'Resource limit'
  if (/timeout|timed out|network|502|503|504|unreachable/i.test(message)) return 'Temporary provider issue'
  return 'Step error'
}

function userMessageForError(category: string | null, message: string): string {
  const cleaned = message.replace(/\s+/g, ' ').trim()

  const jobMatch = cleaned.match(/^Job\s+([^:]+):\s*(.+)$/i)
  const jobPrefix = jobMatch ? `Job ${jobMatch[1]} failed: ` : ''
  const core = jobMatch ? jobMatch[2].trim() : cleaned

  if (/is not defined|ReferenceError/i.test(core)) {
    return `${jobPrefix}the provider hit an internal bug (${core}). Retry may not help until the provider code is fixed.`
  }
  if (/safety|content filter|moderation|blocked/i.test(core)) {
    return `${jobPrefix}the provider blocked this request for safety or content-policy reasons. Try changing the prompt or reference image.`
  }
  if (/quota|credits|balance|limit/i.test(core)) {
    return `${jobPrefix}the provider reported a quota, credits, or rate-limit problem.`
  }
  if (/timeout|timed out|network|502|503|504|unreachable/i.test(core)) {
    return `${jobPrefix}provider connection or server issue. Try again.`
  }
  if (category === 'code_error') {
    return `${jobPrefix}the recipe code for this step failed: ${core}`
  }
  return `${jobPrefix}${core}`
}
