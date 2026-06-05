import { onMounted, onUnmounted } from 'vue';

export interface KeyboardHandlers {
  onUndo?: () => void;
  onRedo?: () => void;
  onDelete?: () => void;
  onEscape?: () => void;
  onNudge?: (dx: number, dy: number) => void;
  /** Return true if text editing is active (to skip delete/backspace handling) */
  isEditingText?: () => boolean;
}

/**
 * Keyboard shortcuts composable
 */
export function useKeyboard(handlers: KeyboardHandlers) {
  function handleKeyDown(event: KeyboardEvent) {
    const { key, ctrlKey, metaKey, shiftKey } = event;
    const cmdOrCtrl = ctrlKey || metaKey;

    // Undo: Ctrl/Cmd + Z
    if (cmdOrCtrl && !shiftKey && key === 'z') {
      event.preventDefault();
      handlers.onUndo?.();
      return;
    }

    // Redo: Ctrl/Cmd + Shift + Z or Ctrl/Cmd + Y
    if ((cmdOrCtrl && shiftKey && key === 'z') || (cmdOrCtrl && key === 'y')) {
      event.preventDefault();
      handlers.onRedo?.();
      return;
    }

    // Delete: Delete or Backspace
    if (key === 'Delete' || key === 'Backspace') {
      // Only if not in an input field or editing text on canvas
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        handlers.isEditingText?.()
      ) {
        return;
      }
      event.preventDefault();
      handlers.onDelete?.();
      return;
    }

    // Escape
    if (key === 'Escape') {
      event.preventDefault();
      handlers.onEscape?.();
      return;
    }

    // Arrow keys for nudging
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)) {
      // Only if not in an input field or editing text on canvas
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        handlers.isEditingText?.()
      ) {
        return;
      }

      event.preventDefault();
      const amount = shiftKey ? 10 : 1;
      const dx =
        key === 'ArrowLeft' ? -amount : key === 'ArrowRight' ? amount : 0;
      const dy =
        key === 'ArrowUp' ? -amount : key === 'ArrowDown' ? amount : 0;
      handlers.onNudge?.(dx, dy);
      return;
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown);
  });

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown);
  });

  return {
    handleKeyDown,
  };
}
