/**
 * Display-time sentence case for labels that arrive from tool schemas.
 *
 * Schema authors often ship Title Case ("Reference Images", "Negative Prompt").
 * The UI voice is sentence case, so de-title them purely for display; the data
 * is never changed. Only a label whose every word is Capitalised is touched,
 * and only plain capitalised words are lowered: acronyms, digits and mixed
 * case ("CFG", "LoRA", "4K", "Top-K") survive, as does the first word.
 */
export function sentenceCaseLabel(label: string | undefined | null): string {
  if (!label) return label ?? ''
  const words = label.split(' ')
  if (words.length < 2) return label
  if (!words.every((w) => /^[A-Z]/.test(w) || /^(a|an|the|of|to|and|or|for|in|on|with|by|per)$/.test(w))) return label
  return words
    .map((w, i) => (i > 0 && /^[A-Z][a-z]+$/.test(w) ? w.toLowerCase() : w))
    .join(' ')
}
