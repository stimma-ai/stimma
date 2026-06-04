/**
 * Prompt processing utilities for wildcards, verbatim text, comments, and LLM enhancements
 *
 * Syntax reference:
 * - [text] - Verbatim text, hidden from auto-improve, preserved in final prompt
 * - {a|b|c} - Wildcard, random selection at generation
 * - # comment - Comment line, guides auto-improve, stripped at generation
 */

export interface WildcardInfo {
  count: number
  examples: string[]
}

export interface VerbatimSegment {
  placeholder: string  // e.g., "VERBATIM_A"
  original: string     // The text inside [[...]]
}

/**
 * Detect wildcards in prompt text
 * Wildcards use the syntax: {option1|option2|option3}
 */
export function detectWildcards(prompt: string): WildcardInfo {
  const regex = /\{([^{}]+\|[^{}]+)\}/g
  const matches = [...prompt.matchAll(regex)]
  return {
    count: matches.length,
    examples: matches.map(m => m[0])
  }
}

/**
 * Named wildcard entry: a named list of values defined in settings
 */
export interface NamedWildcard {
  name: string
  values: string[]
}

/**
 * Prompt segment entry: a named reusable text block defined in settings
 */
export interface PromptSegment {
  name: string
  content: string
}

/**
 * Expand named wildcards and prompt segments.
 * Replaces each {{name}} with either:
 * - A random value from a matching wildcard list, or
 * - The fixed content of a matching prompt segment
 * If no match exists, the token is left as-is.
 */
export function expandNamedWildcards(prompt: string, wildcards: NamedWildcard[], segments?: PromptSegment[]): string {
  if ((!wildcards || wildcards.length === 0) && (!segments || segments.length === 0)) return prompt

  const wildcardLookup = new Map(wildcards.map(w => [w.name.toLowerCase(), w.values]))
  const segmentLookup = new Map((segments || []).map(s => [s.name.toLowerCase(), s.content]))

  return prompt.replace(/\{\{([^{}]+)\}\}/g, (match, name) => {
    const key = name.trim().toLowerCase()
    // Check segments first (fixed content), then wildcards (random pick)
    const segmentContent = segmentLookup.get(key)
    if (segmentContent !== undefined) return segmentContent
    const values = wildcardLookup.get(key)
    if (!values || values.length === 0) return match
    return values[Math.floor(Math.random() * values.length)]
  })
}

/**
 * Expand wildcards by picking random options
 * Replaces each {option1|option2|option3} with a randomly selected option
 * Single options like {foo} expand to just "foo"
 *
 * Any unresolved {{name}} tokens (named wildcards/segments that didn't match)
 * are preserved verbatim rather than collapsed to {name} — otherwise the
 * single-brace pass below would match the inner braces of {{name}}.
 */
export function expandWildcards(prompt: string): string {
  // Protect unresolved {{name}} tokens so the single-brace expansion doesn't
  // cannibalize their inner braces ({{name}} -> {name}). Avoids regex lookbehind
  // for WebKit compatibility (the macOS app runs in WKWebView).
  const protectedTokens: string[] = []
  let result = prompt.replace(/\{\{[^{}]+\}\}/g, (match) => {
    protectedTokens.push(match)
    return `\u0000${protectedTokens.length - 1}\u0000`
  })

  result = result.replace(/\{([^{}]+)\}/g, (match, options) => {
    const choices = options.split('|').map((s: string) => s.trim())
    const randomIndex = Math.floor(Math.random() * choices.length)
    return choices[randomIndex]
  })

  return result.replace(/\u0000(\d+)\u0000/g, (match, index) => protectedTokens[Number(index)])
}

/**
 * Extract [verbatim] segments and replace with placeholders.
 * Used before sending to AI auto-improve.
 */
export function extractVerbatim(prompt: string): {
  processed: string
  segments: VerbatimSegment[]
} {
  const segments: VerbatimSegment[] = []
  let index = 0

  const processed = prompt.replace(/\[([^\[\]]+)\]/g, (match, content) => {
    const placeholder = `__VERBATIM_${String.fromCharCode(65 + index)}__` // A, B, C, ...
    segments.push({ placeholder, original: content })
    index++
    return placeholder
  })

  return { processed, segments }
}

/**
 * Restore verbatim segments from placeholders.
 * Used after receiving AI auto-improve response.
 */
export function restoreVerbatim(prompt: string, segments: VerbatimSegment[]): string {
  let result = prompt
  for (const segment of segments) {
    // Replace placeholder back with original [content]
    result = result.replace(segment.placeholder, `[${segment.original}]`)
  }
  return result
}

/**
 * Verify all verbatim placeholders are present in the output.
 * Returns true if all placeholders are preserved.
 */
export function verifyVerbatimPreserved(output: string, segments: VerbatimSegment[]): boolean {
  for (const segment of segments) {
    if (!output.includes(segment.placeholder)) {
      return false
    }
  }
  return true
}

/**
 * Strip comment lines (lines starting with #) from prompt.
 * Used for final generation - comments guide the AI but aren't sent to image generator.
 */
export function stripComments(prompt: string): string {
  return prompt
    .split('\n')
    .filter(line => !line.trimStart().startsWith('#'))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n') // Collapse multiple blank lines
    .trim()
}

/**
 * Unwrap verbatim [text] markers.
 * The brackets are just markers - final prompt uses the text directly.
 */
export function unwrapVerbatim(prompt: string): string {
  return prompt.replace(/\[([^\[\]]+)\]/g, '$1')
}

/**
 * Process a prompt for final generation.
 * Expands {{name}} first (so segment content gets further processing),
 * then strips comments, unwraps verbatim, expands inline wildcards.
 */
export function processFinalPrompt(prompt: string, wildcards?: NamedWildcard[], segments?: PromptSegment[]): string {
  let result = prompt
  if ((wildcards && wildcards.length > 0) || (segments && segments.length > 0)) {
    result = expandNamedWildcards(result, wildcards || [], segments)
  }
  result = stripComments(result)
  result = unwrapVerbatim(result)
  result = expandWildcards(result)
  return result
}

/**
 * Process a prompt through the full pipeline (client-side parts only)
 * @deprecated Use processFinalPrompt instead for full processing
 */
export function processPromptClientSide(prompt: string): string {
  return expandWildcards(prompt)
}
