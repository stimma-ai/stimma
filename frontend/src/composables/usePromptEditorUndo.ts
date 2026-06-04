import { ref, computed } from 'vue'

/**
 * Coarse-grained undo for the prompt editor.
 *
 * One snapshot = the full editable content of the screen at a point in time
 * (prompt, prompt options, reference images, parameters, markers, categories).
 * The mini-agent takes exactly one snapshot at the start of each run, so a
 * single Undo reverts everything the agent just did, atomically. Pill-applied
 * edits snapshot too.
 *
 * Generic over the snapshot type T — ToolView supplies capture()/restore() that
 * read and write its own reactive state. capture() MUST return a deep copy so
 * later mutations don't alias the stored snapshot.
 */
export interface UndoOptions<T> {
  capture: () => T
  restore: (snap: T) => void
  max?: number
}

export function usePromptEditorUndo<T>(opts: UndoOptions<T>) {
  const undoStack = ref<T[]>([])
  const redoStack = ref<T[]>([])
  const max = opts.max ?? 50

  /** Record the current state as a restore point. Call once before a mutation. */
  function snapshot(): void {
    undoStack.value.push(opts.capture())
    if (undoStack.value.length > max) undoStack.value.shift()
    redoStack.value = []
  }

  function undo(): void {
    if (undoStack.value.length === 0) return
    const current = opts.capture()
    const prev = undoStack.value.pop() as T
    redoStack.value.push(current)
    opts.restore(prev)
  }

  function redo(): void {
    if (redoStack.value.length === 0) return
    const current = opts.capture()
    const next = redoStack.value.pop() as T
    undoStack.value.push(current)
    opts.restore(next)
  }

  function clear(): void {
    undoStack.value = []
    redoStack.value = []
  }

  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)

  return { snapshot, undo, redo, clear, canUndo, canRedo }
}
