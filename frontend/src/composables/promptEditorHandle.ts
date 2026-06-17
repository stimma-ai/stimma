/**
 * Contract a prompt editor exposes so the standalone PromptAgentChat can drive
 * its text in prompt-only mode (flow / image-edit), where edits are applied
 * directly via the single-shot /enhance path rather than the page-wide agent.
 *
 * In full-agent mode (ToolView) the chat never writes the prompt itself — the
 * agent does it through tool calls — so the handle is unused there.
 */
export interface PromptEditorHandle {
  /** Current prompt text. */
  getText: () => string
  /** Replace the prompt text (updates the model + the CodeMirror document). */
  setText: (text: string) => void
  /** Flash an inline word-level diff between two versions of the prompt. */
  animateDiff: (oldText: string, newText: string) => void
}
