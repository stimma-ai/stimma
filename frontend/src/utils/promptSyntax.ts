/**
 * Prompt syntax: what the prompt editor colors, as plain ranges.
 *
 * One tokenizer for every place a prompt is drawn with its syntax: the
 * editor's CodeMirror highlighter (composables/useCodeMirrorPrompt.ts) turns
 * these ranges into marks, and read-only views (the media info panel's
 * "as typed" prompt) turn them into spans with the same colors.
 *
 *   {a|b|c}      a list: one option per image           wildcard
 *   <words>      a slot: Fluent varies it, elsewhere     slot
 *                it is its words
 *   {{name}}     a wildcard or segment                   named-wildcard
 *                (a name that is neither: nothing        unknown-name
 *                fills it, in any mode)
 *   [text]       sent exactly as written                 verbatim
 *   # a note     a line for the chat model               comment
 *                (plain mode: no model reads it)         comment-unread
 */

// How the prompt will be read: drives what is marked.
// enhance: everything is live. plain (Enhance off or no chat model): # lines
// need a model.
// raw: sent exactly as typed, so nothing is special.
export type PromptSyntaxMode = 'enhance' | 'plain' | 'raw'

export type PromptSyntaxKind =
  | 'wildcard'
  | 'named-wildcard'
  | 'unknown-name'
  | 'slot'
  | 'comment'
  | 'comment-unread'
  | 'verbatim'

/** A marked range within one line, in that line's offsets. */
export interface PromptSyntaxRange { from: number; to: number; kind: PromptSyntaxKind }

export interface PromptSyntaxOptions {
  mode?: PromptSyntaxMode
  /** Saved wildcard and segment names, lowercased. Without it no name is marked unknown. */
  known?: ReadonlySet<string>
}

/**
 * A slot: `<` + 2 to 80 characters + `>` on one line, none of `< > { } [ ] | # : =`,
 * not starting with `/` or a space, not ending with a space. The Python side
 * (backend/prompt_programs/slots.py) writes the end check as a lookbehind; this
 * spells it as a last character so older WebKit can parse it. The start must
 * also not follow a letter, digit, `_` or `<` (see `findSlots`). Both sides are
 * tested against slotGrammar.cases.json.
 */
export const SLOT_RE = /<(?![/\s])([^<>{}[\]|#:=\n]{1,79}[^<>{}[\]|#:=\s])>/g
const SLOT_GUARD = /[<\p{L}\p{N}_]/u

/** The marked ranges of one line, sorted by start (ranges may nest). */
export function lineSyntaxRanges(text: string, options: PromptSyntaxOptions = {}): PromptSyntaxRange[] {
  const mode = options.mode ?? 'enhance'
  const known = options.known
  if (mode === 'raw') return []
  // Comment lines: # at start of line
  if (/^\s*#/.test(text)) return [{ from: 0, to: text.length, kind: mode === 'plain' ? 'comment-unread' : 'comment' }]

  const out: PromptSyntaxRange[] = []
  const named = findNamedWildcards(text, known, out)
  const lists = findBraceGroups(text, out, named)
  const verbatim = findVerbatim(text, out)
  for (const [from, to] of lineSlots(text, [...named, ...lists, ...verbatim])) out.push({ from, to, kind: 'slot' })
  return out.sort((a, b) => a.from - b.from)
}

type Span = { from: number; to: number }

function findNamedWildcards(text: string, known: ReadonlySet<string> | undefined, out: PromptSyntaxRange[]) {
  const skip: Span[] = []
  const re = /\{\{([^{}]+)\}\}/g
  let match
  while ((match = re.exec(text)) !== null) {
    const from = match.index
    const to = from + match[0].length
    const unknown = known !== undefined && !known.has(match[1].trim().toLowerCase())
    out.push({ from, to, kind: unknown ? 'unknown-name' : 'named-wildcard' })
    skip.push({ from, to })
  }
  return skip
}

function lineSlots(line: string, skip: Span[]): [number, number][] {
  const out: [number, number][] = []
  const re = new RegExp(SLOT_RE.source, 'g')
  let match
  while ((match = re.exec(line)) !== null) {
    const from = match.index
    if (from > 0 && SLOT_GUARD.test(line[from - 1])) continue
    if (skip.some(r => from >= r.from && from < r.to)) continue
    out.push([from, from + match[0].length])
  }
  return out
}

/** Every slot's span in a whole prompt, brackets included (comment lines skipped). */
export function findSlots(text: string): [number, number][] {
  const out: [number, number][] = []
  let at = 0
  for (const line of text.split('\n')) {
    if (!/^\s*#/.test(line)) {
      const marks: PromptSyntaxRange[] = []
      const named = findNamedWildcards(line, undefined, marks)
      const lists = findBraceGroups(line, marks, named)
      const verbatim = findVerbatim(line, marks)
      for (const [from, to] of lineSlots(line, [...named, ...lists, ...verbatim])) out.push([at + from, at + to])
    }
    at += line.length + 1
  }
  return out
}

function findBraceGroups(text: string, out: PromptSyntaxRange[], skip: Span[]) {
  // Match nested braces containing at least one pipe
  const found: Span[] = []
  let i = 0
  while (i < text.length) {
    // Skip positions inside named wildcard ranges
    if (skip.some(r => i >= r.from && i < r.to)) {
      i++
      continue
    }
    if (text[i] === '{') {
      const start = i
      let depth = 1
      i++
      let hasPipe = false
      while (i < text.length && depth > 0) {
        if (text[i] === '{') depth++
        else if (text[i] === '}') depth--
        else if (text[i] === '|' && depth === 1) hasPipe = true
        i++
      }
      if (depth === 0 && hasPipe) {
        out.push({ from: start, to: i, kind: 'wildcard' })
        found.push({ from: start, to: i })
      }
    } else {
      i++
    }
  }
  return found
}

function findVerbatim(text: string, out: PromptSyntaxRange[]) {
  const found: Span[] = []
  const re = /\[([^\]]+)\]/g
  let match
  while ((match = re.exec(text)) !== null) {
    out.push({ from: match.index, to: match.index + match[0].length, kind: 'verbatim' })
    found.push({ from: match.index, to: match.index + match[0].length })
  }
  return found
}

/** A run of text with one look: `kind` is the innermost mark over it, or null. */
export interface PromptSyntaxSpan { text: string; kind: PromptSyntaxKind | null }

/**
 * The whole prompt cut into runs for a read-only view. Where marks nest
 * (`{a|[b]}`), a run takes the innermost one, as the editor draws it.
 */
export function promptSyntaxSpans(text: string, options: PromptSyntaxOptions = {}): PromptSyntaxSpan[] {
  const spans: PromptSyntaxSpan[] = []
  const push = (part: string, kind: PromptSyntaxKind | null) => {
    if (!part) return
    const last = spans[spans.length - 1]
    if (last && last.kind === kind) last.text += part
    else spans.push({ text: part, kind })
  }
  const lines = text.split('\n')
  lines.forEach((line, n) => {
    const ranges = lineSyntaxRanges(line, options)
    const cuts = [...new Set([0, line.length, ...ranges.flatMap(r => [r.from, r.to])])].sort((a, b) => a - b)
    for (let c = 0; c < cuts.length - 1; c++) {
      const from = cuts[c]
      const to = cuts[c + 1]
      let inner: PromptSyntaxRange | null = null
      for (const r of ranges) {
        if (r.from <= from && r.to >= to && (!inner || r.from > inner.from || (r.from === inner.from && r.to < inner.to))) inner = r
      }
      push(line.slice(from, to), inner?.kind ?? null)
    }
    if (n < lines.length - 1) push('\n', null)
  })
  return spans
}

/**
 * The editor's syntax colors as Tailwind classes, for read-only views. Keep in
 * step with the `.cm-*` rules in useCodeMirrorPrompt.ts's theme.
 */
export const PROMPT_SYNTAX_CLASS: Record<PromptSyntaxKind, string> = {
  'wildcard': 'text-green-600 bg-green-500/10 rounded-[2px] px-px',
  'named-wildcard': 'text-amber-600 bg-amber-500/10 rounded-[2px] px-px',
  'unknown-name': 'text-red-500 underline decoration-wavy decoration-red-500/80 underline-offset-[3px]',
  'slot': 'text-violet-600 bg-violet-500/10 rounded-[2px] px-px',
  'comment': 'text-gray-500 italic',
  'comment-unread': 'text-gray-500 italic',
  'verbatim': 'text-blue-500 bg-blue-500/10 rounded-[2px] px-px',
}
