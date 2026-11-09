// A prompt program run, as the generation details show it: one row per roll, each the
// prompt with its drawn values inline. A roll after the first marks what changed: the
// value it replaced (struck) beside the new one. Everything comes from the run record
// (each fix round's text, spans and values, or the run's own view), never from
// searching the prompt.

export interface RollPiece {
  text: string
  /** A drawn value: the choice's id. */
  id?: string
  /** The value this roll replaced (the previous roll's value for this choice). */
  was?: string
  /** P(wrong) the judge gave the replaced value, when it was the one rerolled. */
  score?: number
}

export interface Roll {
  pieces: RollPiece[]
  /** The roll whose image this is. */
  used: boolean
}

interface RollRecord {
  text?: string
  spans?: Array<[number, number, string]>
  values?: Record<string, string>
  scores?: Record<string, number | null>
  rerolled?: { id: string; value: string; failed?: boolean }
}

function isRoll(r: any): r is RollRecord {
  return !!r && typeof r.text === 'string' && Array.isArray(r.spans)
}

function pieces(roll: RollRecord, prev: RollRecord | null): RollPiece[] {
  const out: RollPiece[] = []
  const text = roll.text || ''
  let at = 0
  for (const [start, end, id] of roll.spans || []) {
    if (start < at || end > text.length || end <= start) continue
    if (start > at) out.push({ text: text.slice(at, start) })
    const piece: RollPiece = { text: text.slice(start, end), id }
    const before = prev?.values?.[id]
    if (before != null && before !== roll.values?.[id]) {
      piece.was = before
      const score = prev?.rerolled?.id === id ? prev?.scores?.[id] : null
      if (typeof score === 'number') piece.score = score
    }
    out.push(piece)
    at = end
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}

/** The rows for a run record (`prompt_program` in a generation's metadata). */
export function promptProgramRolls(run: any): Roll[] {
  if (!run) return []
  const rounds: any[] = Array.isArray(run.fix?.rounds) ? run.fix.rounds : []
  if (rounds.length && rounds.every(isRoll)) {
    const chosen = Number.isInteger(run.fix.chosen) ? run.fix.chosen : rounds.length - 1
    return rounds.map((r, i) => ({ pieces: pieces(r, i ? rounds[i - 1] : null), used: i === chosen }))
  }
  if (isRoll(run.view)) return [{ pieces: pieces(run.view, null), used: true }]
  // Recorded before rolls were: the prompt alone.
  return typeof run.prompt === 'string' && run.prompt ? [{ pieces: [{ text: run.prompt }], used: true }] : []
}
