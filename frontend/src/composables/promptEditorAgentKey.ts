import type { InjectionKey, Ref, ComputedRef } from 'vue'
import type { AgentMessage } from './usePromptMiniAgent'

/**
 * Shape of the object ToolView provides and AIPromptEditor injects.
 * Bundles the mini-agent loop driver (send/running/error/lastReply/messages/
 * clearHistory) with the coarse-grained undo controls so the feedback box and
 * Undo/Redo buttons drive the single shared system in ToolView.
 *
 * AIPromptEditor guards every access with optional chaining so it keeps working
 * standalone (e.g. recipe context) when the inject is absent.
 */
export interface PromptEditorAgent {
  send: (text: string) => Promise<void>
  running: Ref<boolean>
  error: Ref<string | null>
  lastReply: Ref<string>
  messages: Ref<AgentMessage[]>
  clearHistory: () => void
  /** Extended-thinking toggle — a persisted per-tool setting (default off). */
  thinking: Ref<boolean>
  /** Take a coarse-grained undo snapshot (used before pill-applied edits). */
  snapshot: () => void
  undo: () => void
  redo: () => void
  canUndo: ComputedRef<boolean>
  canRedo: ComputedRef<boolean>
}

export const PROMPT_EDITOR_AGENT_KEY: InjectionKey<PromptEditorAgent> = Symbol('promptEditorAgent')
