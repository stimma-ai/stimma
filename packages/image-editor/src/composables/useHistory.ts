import { ref, computed, markRaw, shallowRef, triggerRef } from 'vue';
import type { EditorState, HistoryEntry } from '@/types';
import { HISTORY_CONFIG, TIMING } from '@/constants';

/**
 * Fields that contain large data (canvas snapshots or base64 data URLs).
 * These are excluded from JSON stringify/parse and handled specially.
 * Canvas snapshots are cloned via drawImage (~1ms).
 * Strings are copied by reference (safe since strings are immutable).
 */
const LARGE_DATA_FIELDS: (keyof EditorState)[] = [
  'retouchLayerData',
  'selectionMaskData',
];

/**
 * Clone a large data field value. Supports both HTMLCanvasElement snapshots
 * and legacy string data URLs.
 */
function cloneLargeField(value: any): any {
  if (value instanceof HTMLCanvasElement) {
    // Clone canvas via drawImage (~1ms), markRaw to prevent Vue deep proxying
    const clone = document.createElement('canvas');
    clone.width = value.width;
    clone.height = value.height;
    const ctx = clone.getContext('2d');
    if (ctx) {
      ctx.drawImage(value, 0, 0);
    }
    return markRaw(clone);
  }
  // Strings are immutable, safe to share by reference
  return value;
}

/**
 * Clone editor state via shallow copy + canvas snapshot cloning.
 *
 * Shallow copy is safe because all state mutations create new objects:
 * - updateState() does { ...state, ...partial }
 * - updateShape() creates new annotations array via .map() with spread shapes
 * - Crop, brush settings, colors etc. are always replaced, never mutated
 * Canvas snapshots (retouchLayerData, selectionMaskData) need real clones
 * since they're mutable pixel buffers.
 */
function cloneState(state: EditorState): EditorState {
  const cloned = { ...state };

  // Clone canvas snapshots (mutable pixel buffers need real copies)
  for (const field of LARGE_DATA_FIELDS) {
    const value = state[field];
    if (value !== undefined && value !== null) {
      (cloned as any)[field] = cloneLargeField(value);
    }
  }

  return cloned;
}

/**
 * History manager composable for undo/redo functionality
 */
export function useHistory(
  getState: () => EditorState,
  setState: (state: EditorState) => void
) {
  const entries = shallowRef<HistoryEntry[]>([]);
  const currentIndex = ref(-1);
  const maxEntries = HISTORY_CONFIG.maxEntries;
  let debounceTimer: number | null = null;

  const canUndo = computed(() => currentIndex.value > 0);
  const canRedo = computed(() => currentIndex.value < entries.value.length - 1);

  /**
   * Push a new state to history
   */
  function push(action: string) {
    // Clear any pending debounce
    if (debounceTimer !== null) {
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }

    // Debounce rapid state changes
    debounceTimer = window.setTimeout(() => {
      const state = getState();
      const entry: HistoryEntry = {
        state: cloneState(state),
        timestamp: Date.now(),
        action,
      };

      // Remove any redo entries if we're not at the end
      if (currentIndex.value < entries.value.length - 1) {
        entries.value = entries.value.slice(0, currentIndex.value + 1);
      }

      // Add new entry
      entries.value.push(entry);

      // Trim to max size
      if (entries.value.length > maxEntries) {
        entries.value = entries.value.slice(entries.value.length - maxEntries);
      }

      currentIndex.value = entries.value.length - 1;
      triggerRef(entries);
      debounceTimer = null;
    }, TIMING.historyDebounce);
  }

  /**
   * Push immediately without debouncing
   */
  function pushImmediate(action: string) {
    if (debounceTimer !== null) {
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }

    const state = getState();
    const entry: HistoryEntry = {
      state: cloneState(state),
      timestamp: Date.now(),
      action,
    };

    if (currentIndex.value < entries.value.length - 1) {
      entries.value = entries.value.slice(0, currentIndex.value + 1);
    }

    entries.value.push(entry);

    if (entries.value.length > maxEntries) {
      entries.value = entries.value.slice(entries.value.length - maxEntries);
    }

    currentIndex.value = entries.value.length - 1;
    triggerRef(entries);
  }

  /**
   * Undo to previous state
   */
  function undo(): EditorState | null {
    if (!canUndo.value) return null;

    currentIndex.value--;
    const entry = entries.value[currentIndex.value];
    const state = cloneState(entry.state);
    setState(state);
    return state;
  }

  /**
   * Return cloned undo state WITHOUT calling setState.
   * Caller is responsible for merging UI fields and setting state.
   */
  function undoState(): EditorState | null {
    if (!canUndo.value) return null;
    currentIndex.value--;
    return cloneState(entries.value[currentIndex.value].state);
  }

  /**
   * Redo to next state
   */
  function redo(): EditorState | null {
    if (!canRedo.value) return null;

    currentIndex.value++;
    const entry = entries.value[currentIndex.value];
    const state = cloneState(entry.state);
    setState(state);
    return state;
  }

  /**
   * Return cloned redo state WITHOUT calling setState.
   * Caller is responsible for merging UI fields and setting state.
   */
  function redoState(): EditorState | null {
    if (!canRedo.value) return null;
    currentIndex.value++;
    return cloneState(entries.value[currentIndex.value].state);
  }

  /**
   * Clear all history
   */
  function clear() {
    if (debounceTimer !== null) {
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    entries.value = [];
    currentIndex.value = -1;
    triggerRef(entries);
  }

  /**
   * Get the initial state (for revert)
   */
  function getInitialState(): EditorState | null {
    if (entries.value.length === 0) return null;
    return cloneState(entries.value[0].state);
  }

  /**
   * Revert to initial state
   */
  function revert(): EditorState | null {
    const initial = getInitialState();
    if (!initial) return null;

    currentIndex.value = 0;
    setState(initial);
    return initial;
  }

  /**
   * Return cloned initial state WITHOUT calling setState.
   * Caller is responsible for merging UI fields and setting state.
   */
  function revertState(): EditorState | null {
    const initial = getInitialState();
    if (!initial) return null;
    currentIndex.value = 0;
    return initial;
  }

  /**
   * Load history state directly (for project deserialization)
   */
  function loadHistory(
    newEntries: HistoryEntry[],
    newCurrentIndex: number
  ) {
    if (debounceTimer !== null) {
      window.clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    entries.value = newEntries.map(entry => ({
      ...entry,
      state: cloneState(entry.state),
    }));
    currentIndex.value = newCurrentIndex;
    triggerRef(entries);

    // Apply the current state
    if (newCurrentIndex >= 0 && newCurrentIndex < entries.value.length) {
      const state = cloneState(entries.value[newCurrentIndex].state);
      setState(state);
    }
  }

  /**
   * Get all history entries (for serialization)
   */
  function getEntries(): HistoryEntry[] {
    return entries.value.map(entry => ({
      ...entry,
      state: cloneState(entry.state),
    }));
  }

  /**
   * Get current history index (for serialization)
   */
  function getCurrentIndex(): number {
    return currentIndex.value;
  }

  return {
    entries,
    currentIndex,
    canUndo,
    canRedo,
    push,
    pushImmediate,
    undo,
    undoState,
    redo,
    redoState,
    clear,
    getInitialState,
    revert,
    revertState,
    loadHistory,
    getEntries,
    getCurrentIndex,
  };
}

export type HistoryManager = ReturnType<typeof useHistory>;
