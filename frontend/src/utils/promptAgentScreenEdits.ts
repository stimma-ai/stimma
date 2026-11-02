/**
 * What the user changed by hand between prompt-agent turns.
 *
 * The user and the agent edit the same text by turns, but only the agent's edits
 * appear in the conversation: its old tool calls still spell out text the user
 * has since replaced or cleared. Recording the user's edits as turns of their
 * own keeps that history honest (the backend renders them for the model).
 */
export interface ScreenEdit {
  field: 'prompt' | 'instructions'
  before: string
  after: string
}

export type CoEditedText = Partial<Record<ScreenEdit['field'], string>>

/** The co-edited text in a state_context. A field the screen lacks stays absent. */
export function coEditedText(state: Record<string, any>): CoEditedText {
  const text: CoEditedText = {}
  if (typeof state.prompt === 'string') text.prompt = state.prompt
  if (typeof state.notes?.instructions === 'string') text.instructions = state.notes.instructions
  return text
}

/** Fields that differ between what the agent last saw and the screen now. */
export function screenEditsSince(seen: CoEditedText, now: CoEditedText): ScreenEdit[] {
  const edits: ScreenEdit[] = []
  for (const field of ['prompt', 'instructions'] as const) {
    const before = seen[field]
    const after = now[field]
    if (before === undefined || after === undefined) continue
    if (before.trim() !== after.trim()) edits.push({ field, before, after })
  }
  return edits
}

/**
 * Move what the agent has seen past one of its own tool calls. Only fields the
 * tool changed advance, so a hand edit made while a request was in flight is
 * still reported on the next turn.
 */
export function afterAgentTool(seen: CoEditedText, before: CoEditedText, after: CoEditedText): CoEditedText {
  const next = { ...seen }
  for (const field of ['prompt', 'instructions'] as const) {
    if (before[field] !== after[field]) next[field] = after[field]
  }
  return next
}

export function isPromptCleared(edit: ScreenEdit): boolean {
  return edit.field === 'prompt' && !edit.after.trim()
}
