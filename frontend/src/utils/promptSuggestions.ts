/**
 * The shapes of Fluent's Suggest answer, and the pure checks on them (the composable that
 * asks is composables/usePromptSuggestions.ts).
 *
 * vary   phrases the user wrote that could change from picture to picture: underlined in the
 *        text, and a chip; a click wraps the words in brackets.
 * looks  complete descriptions of how the picture is shot or made; a click adds the words.
 * adds   concrete things the picture lacks; a click adds the words.
 */

/** A phrase that could vary: `mode` 'one' fleshes out one specific thing (the same thing shown
    different ways), 'kind' varies it (a different one of its kind). */
export interface SuggestedPhrase { from: number; to: number; text: string; label: string; mode: 'one' | 'kind' }
/** Fixed words a click writes into the prompt as they are, and the chip's label. */
export interface SuggestedWords { text: string; label: string }
export interface Suggestions { vary: SuggestedPhrase[]; looks: SuggestedWords[]; adds: SuggestedWords[] }

const words = (list: any): SuggestedWords[] => Array.isArray(list)
  ? list.filter((w: any) => typeof w?.text === 'string' && w.text.trim())
    .map((w: any) => ({ text: w.text, label: typeof w.label === 'string' && w.label.trim() ? w.label : w.text }))
  : []

/** A /suggest answer, keeping only well-formed parts. */
export function cleanSuggestions(data: any): Suggestions {
  const vary = Array.isArray(data?.vary) ? data.vary
    .filter((p: any) => Number.isInteger(p?.from) && Number.isInteger(p?.to) && typeof p?.text === 'string')
    .map((p: any): SuggestedPhrase => ({ from: p.from, to: p.to, text: p.text,
      label: typeof p.label === 'string' && p.label.trim() ? p.label : p.text,
      mode: p.mode === 'one' ? 'one' : 'kind' })) : []
  return { vary, looks: words(data?.looks), adds: words(data?.adds) }
}

const isNote = (line: string) => /^\s*#/.test(line)

/** The prompt with `words` added after a comma at the end of its last picture line (not a
    # note line); just the words when there is none. */
export function appendWords(prompt: string, words: string): string {
  const lines = prompt.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].trim() || isNote(lines[i])) continue
    const end = lines[i].trimEnd().length
    const head = lines[i].slice(0, end)
    lines[i] = `${head}${/[,;]$/.test(head) ? ' ' : ', '}${words}${lines[i].slice(end)}`
    return lines.join('\n')
  }
  return prompt.trim() ? `${prompt.replace(/\n+$/, '')}\n${words}` : words
}

/** The fixed words worth showing for the prompt as it stands: none of the looks once one is
    in it, and no add that is already there. */
export function shownWords(s: Suggestions, prompt: string): { looks: SuggestedWords[]; adds: SuggestedWords[] } {
  const looks = s.looks.some(l => prompt.includes(l.text)) ? [] : s.looks
  return { looks, adds: s.adds.filter(a => !prompt.includes(a.text)) }
}
