/**
 * Canvas-based text editing composable
 * Handles cursor, selection, keyboard input for editing text annotations directly on canvas
 */
import { ref, onUnmounted } from 'vue';
import type { Ref } from 'vue';
import type { Point, Size, ViewTransform } from '@/types';
import type { TextShape, Shape } from '@/types/shapes';
import { TEXT_BASE_FONT_SIZE } from '@/types/shapes';
import type { TextEditState } from '@/utils/shapes';
import { measureTextBase, toPixels, getShapeBounds } from '@/utils/shapes';
import { screenToCanvas, canvasToImage } from '@/utils/canvas';

export interface UseTextEditingOptions {
  canvasRef: Ref<HTMLCanvasElement | null>;
  viewTransform: Ref<ViewTransform>;
  imageSize: Ref<Size | null>;
  canvasSize: Ref<Size>;
  getAnnotations: () => Shape[];
  updateShape: (shapeId: string, updates: Partial<Shape>) => void;
  onStopEditing?: () => void;
}

export function useTextEditing(options: UseTextEditingOptions) {
  const {
    canvasRef,
    viewTransform,
    imageSize,
    canvasSize,
    getAnnotations,
    updateShape,
    onStopEditing,
  } = options;

  const editState = ref<TextEditState | null>(null);
  let blinkInterval: number | null = null;
  let originalText: string = '';
  const autoFitShapeIds = new Set<string>();
  const autoFitInitialScaleByShapeId = new Map<string, number>();

  /**
   * Get the text shape being edited
   */
  function getEditingShape(): TextShape | null {
    if (!editState.value) return null;
    const shape = getAnnotations().find(s => s.id === editState.value!.shapeId);
    return (shape && shape.type === 'text') ? shape as TextShape : null;
  }

  /**
   * Start editing a text shape
   * By default, selects all text. Pass selectAll=false to just place cursor.
   */
  function startEditing(
    shapeId: string,
    initialCursor?: number,
    selectAll: boolean = true,
    autoFitWhileEditing: boolean = true
  ) {
    const shape = getAnnotations().find(s => s.id === shapeId);
    if (!shape || shape.type !== 'text') return;

    const textShape = shape as TextShape;
    originalText = textShape.text;

    // If selectAll is true and there's text, select all of it
    // Otherwise, set cursor at the specified position or end
    const hasText = textShape.text.length > 0;
    const cursorIndex = initialCursor ?? textShape.text.length;

    editState.value = {
      shapeId,
      cursorIndex: selectAll && hasText ? textShape.text.length : cursorIndex,
      selectionAnchor: selectAll && hasText ? 0 : null,
      cursorVisible: true,
    };

    if (autoFitWhileEditing) {
      autoFitShapeIds.add(shapeId);
      const initialScale = textShape.baseHeight > 0 ? textShape.height / textShape.baseHeight : 1;
      autoFitInitialScaleByShapeId.set(shapeId, Math.max(0.05, initialScale));
    } else {
      autoFitShapeIds.delete(shapeId);
      autoFitInitialScaleByShapeId.delete(shapeId);
    }

    // Start cursor blinking
    startBlinking();
  }

  /**
   * Stop editing and commit changes
   */
  function stopEditing(commit: boolean = true) {
    if (!editState.value) return;

    const shapeId = editState.value.shapeId;
    stopBlinking();

    if (!commit) {
      // Revert to original text
      const shape = getEditingShape();
      if (shape && shape.text !== originalText) {
        updateShape(editState.value.shapeId, { text: originalText });
      }
    }

    editState.value = null;
    autoFitShapeIds.delete(shapeId);
    autoFitInitialScaleByShapeId.delete(shapeId);
    onStopEditing?.();
  }

  /**
   * Start cursor blinking
   */
  function startBlinking() {
    stopBlinking();
    blinkInterval = window.setInterval(() => {
      if (editState.value) {
        editState.value = {
          ...editState.value,
          cursorVisible: !editState.value.cursorVisible,
        };
      }
    }, 500);
  }

  /**
   * Stop cursor blinking
   */
  function stopBlinking() {
    if (blinkInterval !== null) {
      clearInterval(blinkInterval);
      blinkInterval = null;
    }
  }

  /**
   * Reset cursor blink (show cursor and restart blink timer)
   */
  function resetBlink() {
    if (editState.value) {
      editState.value = { ...editState.value, cursorVisible: true };
    }
    startBlinking();
  }

  /**
   * Handle keyboard input
   */
  function handleKeyDown(event: KeyboardEvent): boolean {
    if (!editState.value) return false;

    const shape = getEditingShape();
    if (!shape) return false;

    const { cursorIndex, selectionAnchor } = editState.value;
    const text = shape.text;
    const hasSelection = selectionAnchor !== null && selectionAnchor !== cursorIndex;
    const selStart = hasSelection ? Math.min(selectionAnchor!, cursorIndex) : cursorIndex;
    const selEnd = hasSelection ? Math.max(selectionAnchor!, cursorIndex) : cursorIndex;

    // Handle shortcuts
    if (event.ctrlKey || event.metaKey) {
      switch (event.key.toLowerCase()) {
        case 'a': // Select all
          event.preventDefault();
          editState.value = {
            ...editState.value,
            cursorIndex: text.length,
            selectionAnchor: 0,
          };
          resetBlink();
          return true;

        case 'c': // Copy
          if (hasSelection) {
            event.preventDefault();
            const selectedText = text.substring(selStart, selEnd);
            navigator.clipboard.writeText(selectedText);
          }
          return true;

        case 'x': // Cut
          if (hasSelection) {
            event.preventDefault();
            const selectedText = text.substring(selStart, selEnd);
            navigator.clipboard.writeText(selectedText);
            const newText = text.substring(0, selStart) + text.substring(selEnd);
            applyTextChange(newText, selStart);
          }
          return true;

        case 'v': // Paste
          event.preventDefault();
          navigator.clipboard.readText().then(clipboardText => {
            if (!clipboardText) return;
            const newText = text.substring(0, selStart) + clipboardText + text.substring(selEnd);
            applyTextChange(newText, selStart + clipboardText.length);
          });
          return true;
      }
    }

    switch (event.key) {
      case 'Escape':
        event.preventDefault();
        stopEditing(true); // Commit on escape
        return true;

      case 'Enter':
        if (event.shiftKey) {
          // Shift+Enter inserts newline
          event.preventDefault();
          const newText = text.substring(0, selStart) + '\n' + text.substring(selEnd);
          applyTextChange(newText, selStart + 1);
        } else {
          // Enter commits editing
          event.preventDefault();
          stopEditing(true);
        }
        return true;

      case 'Backspace':
        event.preventDefault();
        if (hasSelection) {
          const newText = text.substring(0, selStart) + text.substring(selEnd);
          applyTextChange(newText, selStart);
        } else if (cursorIndex > 0) {
          const newText = text.substring(0, cursorIndex - 1) + text.substring(cursorIndex);
          applyTextChange(newText, cursorIndex - 1);
        }
        return true;

      case 'Delete':
        event.preventDefault();
        if (hasSelection) {
          const newText = text.substring(0, selStart) + text.substring(selEnd);
          applyTextChange(newText, selStart);
        } else if (cursorIndex < text.length) {
          const newText = text.substring(0, cursorIndex) + text.substring(cursorIndex + 1);
          applyTextChange(newText, cursorIndex);
        }
        return true;

      case 'ArrowLeft':
        event.preventDefault();
        moveCursor(-1, event.shiftKey, event.ctrlKey || event.metaKey);
        return true;

      case 'ArrowRight':
        event.preventDefault();
        moveCursor(1, event.shiftKey, event.ctrlKey || event.metaKey);
        return true;

      case 'ArrowUp':
        event.preventDefault();
        moveCursorVertically(-1, event.shiftKey);
        return true;

      case 'ArrowDown':
        event.preventDefault();
        moveCursorVertically(1, event.shiftKey);
        return true;

      case 'Home':
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
          // Go to start of text
          const newCursor = 0;
          updateCursorPosition(newCursor, event.shiftKey);
        } else {
          // Go to start of line
          const lineStart = findLineStart(text, cursorIndex);
          updateCursorPosition(lineStart, event.shiftKey);
        }
        return true;

      case 'End':
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
          // Go to end of text
          const newCursor = text.length;
          updateCursorPosition(newCursor, event.shiftKey);
        } else {
          // Go to end of line
          const lineEnd = findLineEnd(text, cursorIndex);
          updateCursorPosition(lineEnd, event.shiftKey);
        }
        return true;

      default:
        // Handle printable characters
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
          event.preventDefault();
          const newText = text.substring(0, selStart) + event.key + text.substring(selEnd);
          applyTextChange(newText, selStart + 1);
          return true;
        }
    }

    return false;
  }

  /**
   * Apply text change and update shape
   */
  function applyTextChange(newText: string, newCursor: number) {
    const shape = getEditingShape();
    if (!shape || !editState.value) return;

    // Measure new text dimensions (including shadow effect if present)
    const measured = measureTextBase(
      newText,
      shape.fontFamily,
      shape.fontWeight,
      shape.fontStyle,
      shape.textEffect,
      shape.shadowLength,
      shape.shadowDirection
    );
    const imgSize = imageSize.value;
    const newBaseWidth = imgSize ? measured.width / imgSize.width : shape.baseWidth;
    const newBaseHeight = imgSize ? measured.height / imgSize.height : shape.baseHeight;

    // Calculate current scale
    const currentScale = shape.baseHeight > 0 ? shape.height / shape.baseHeight : 1;

    let nextScale = currentScale;

    // Only during first text-entry session: shrink to keep text bounds on-screen.
    // Subsequent edits preserve whatever scale the shape currently has.
    if (autoFitShapeIds.has(shape.id)) {
      const availableWidth = Math.max(0.001, 1 - shape.x);
      const availableHeight = Math.max(0.001, 1 - shape.y);
      const maxScaleByWidth = newBaseWidth > 0 ? availableWidth / newBaseWidth : Number.POSITIVE_INFINITY;
      const maxScaleByHeight = newBaseHeight > 0 ? availableHeight / newBaseHeight : Number.POSITIVE_INFINITY;
      const maxAllowedScale = Math.min(maxScaleByWidth, maxScaleByHeight);
      const initialScale = autoFitInitialScaleByShapeId.get(shape.id) ?? currentScale;
      const desiredScale = Math.min(initialScale, maxAllowedScale);

      if (Number.isFinite(desiredScale)) {
        // Reversible during first entry: typing can shrink, deleting can grow back
        // up to the initial entry scale.
        nextScale = Math.max(0.05, desiredScale);
      }
    }

    const newWidth = newBaseWidth * nextScale;
    const newHeight = newBaseHeight * nextScale;

    updateShape(editState.value.shapeId, {
      text: newText,
      width: newWidth,
      height: newHeight,
      baseWidth: newBaseWidth,
      baseHeight: newBaseHeight,
    });

    editState.value = {
      ...editState.value,
      cursorIndex: newCursor,
      selectionAnchor: null,
    };

    resetBlink();
  }

  /**
   * Move cursor by delta
   */
  function moveCursor(delta: number, extendSelection: boolean, wordJump: boolean) {
    const shape = getEditingShape();
    if (!shape || !editState.value) return;

    const { cursorIndex } = editState.value;
    const text = shape.text;
    let newCursor = cursorIndex;

    if (wordJump) {
      // Jump by word
      if (delta < 0) {
        newCursor = findWordBoundary(text, cursorIndex, -1);
      } else {
        newCursor = findWordBoundary(text, cursorIndex, 1);
      }
    } else {
      newCursor = Math.max(0, Math.min(text.length, cursorIndex + delta));
    }

    updateCursorPosition(newCursor, extendSelection);
  }

  /**
   * Move cursor vertically (up/down lines)
   */
  function moveCursorVertically(direction: number, extendSelection: boolean) {
    const shape = getEditingShape();
    if (!shape || !editState.value) return;

    const { cursorIndex } = editState.value;
    const text = shape.text;
    const lines = text.split('\n');

    // Find current line and column
    let charCount = 0;
    let currentLine = 0;
    let currentCol = 0;

    for (let i = 0; i < lines.length; i++) {
      const lineLength = lines[i].length;
      if (charCount + lineLength >= cursorIndex) {
        currentLine = i;
        currentCol = cursorIndex - charCount;
        break;
      }
      charCount += lineLength + 1;
      if (i === lines.length - 1) {
        currentLine = i;
        currentCol = lineLength;
      }
    }

    // Move to target line
    const targetLine = Math.max(0, Math.min(lines.length - 1, currentLine + direction));
    if (targetLine === currentLine) {
      // At top/bottom, move to start/end
      if (direction < 0) {
        updateCursorPosition(0, extendSelection);
      } else {
        updateCursorPosition(text.length, extendSelection);
      }
      return;
    }

    // Calculate new cursor position
    const targetCol = Math.min(currentCol, lines[targetLine].length);
    let newCursor = 0;
    for (let i = 0; i < targetLine; i++) {
      newCursor += lines[i].length + 1;
    }
    newCursor += targetCol;

    updateCursorPosition(newCursor, extendSelection);
  }

  /**
   * Update cursor position, optionally extending selection
   */
  function updateCursorPosition(newCursor: number, extendSelection: boolean) {
    if (!editState.value) return;

    const { cursorIndex, selectionAnchor } = editState.value;

    if (extendSelection) {
      // Extend selection
      editState.value = {
        ...editState.value,
        cursorIndex: newCursor,
        selectionAnchor: selectionAnchor ?? cursorIndex,
      };
    } else {
      // Clear selection and move cursor
      editState.value = {
        ...editState.value,
        cursorIndex: newCursor,
        selectionAnchor: null,
      };
    }

    resetBlink();
  }

  /**
   * Find word boundary for word-jump navigation
   */
  function findWordBoundary(text: string, pos: number, direction: number): number {
    if (direction < 0) {
      // Moving left: skip whitespace, then find start of word
      let i = pos - 1;
      while (i > 0 && /\s/.test(text[i])) i--;
      while (i > 0 && !/\s/.test(text[i - 1])) i--;
      return Math.max(0, i);
    } else {
      // Moving right: skip current word, then skip whitespace
      let i = pos;
      while (i < text.length && !/\s/.test(text[i])) i++;
      while (i < text.length && /\s/.test(text[i])) i++;
      return Math.min(text.length, i);
    }
  }

  /**
   * Find start of current line
   */
  function findLineStart(text: string, pos: number): number {
    let i = pos;
    while (i > 0 && text[i - 1] !== '\n') i--;
    return i;
  }

  /**
   * Find end of current line
   */
  function findLineEnd(text: string, pos: number): number {
    let i = pos;
    while (i < text.length && text[i] !== '\n') i++;
    return i;
  }

  /**
   * Convert screen point to image coordinates
   */
  function toImagePoint(screenPoint: Point): Point | null {
    const canvas = canvasRef.value;
    const imgSize = imageSize.value;
    if (!canvas || !imgSize) return null;

    const rect = canvas.getBoundingClientRect();
    const canvasPoint = screenToCanvas(screenPoint, rect);
    return canvasToImage(canvasPoint, viewTransform.value, imgSize, canvasSize.value);
  }

  /**
   * Handle click to position cursor
   */
  function handleClick(screenPoint: Point) {
    const shape = getEditingShape();
    if (!shape || !editState.value) return;

    const imagePoint = toImagePoint(screenPoint);
    if (!imagePoint) return;

    const cursorIndex = getCursorIndexAtPoint(shape, imagePoint);
    if (cursorIndex !== null) {
      editState.value = {
        ...editState.value,
        cursorIndex,
        selectionAnchor: null,
      };
      resetBlink();
    }
  }

  /**
   * Handle double-click to select word
   */
  function handleDoubleClick(screenPoint: Point) {
    const shape = getEditingShape();
    if (!shape || !editState.value) return;

    const imagePoint = toImagePoint(screenPoint);
    if (!imagePoint) return;

    const cursorIndex = getCursorIndexAtPoint(shape, imagePoint);
    if (cursorIndex === null) return;

    const text = shape.text;

    // Find word boundaries
    let wordStart = cursorIndex;
    let wordEnd = cursorIndex;

    // Expand to word boundaries
    while (wordStart > 0 && !/\s/.test(text[wordStart - 1])) wordStart--;
    while (wordEnd < text.length && !/\s/.test(text[wordEnd])) wordEnd++;

    if (wordStart < wordEnd) {
      editState.value = {
        ...editState.value,
        cursorIndex: wordEnd,
        selectionAnchor: wordStart,
      };
      resetBlink();
    }
  }

  /**
   * Get cursor index at a point in the text shape
   */
  function getCursorIndexAtPoint(shape: TextShape, imagePoint: Point): number | null {
    const imgSize = imageSize.value;
    if (!imgSize) return null;

    const bounds = getShapeBounds(shape, imgSize);

    // Transform point to shape's local coordinate system
    const centerX = bounds.x + bounds.width / 2;
    const centerY = bounds.y + bounds.height / 2;

    // Rotate point by -rotation around shape center
    const cos = Math.cos(-shape.rotation);
    const sin = Math.sin(-shape.rotation);
    const dx = imagePoint.x - centerX;
    const dy = imagePoint.y - centerY;
    const localX = centerX + dx * cos - dy * sin;
    const localY = centerY + dx * sin + dy * cos;

    // Convert to position within the shape bounds
    const relX = localX - bounds.x;
    const relY = localY - bounds.y;

    // Calculate scale
    const scale = bounds.height / shape.baseHeight;

    // Convert to base coordinate space
    const baseX = relX / scale;
    const baseY = relY / scale;

    // Convert base coordinates to pixels
    const baseWidthPx = toPixels(shape.baseWidth, imgSize.width);

    const pixelX = baseX * imgSize.width;
    const pixelY = baseY * imgSize.height;

    // Find which line was clicked
    const lineHeight = TEXT_BASE_FONT_SIZE * 1.2;
    const lines = shape.text.split('\n');
    const lineIndex = Math.max(0, Math.min(lines.length - 1, Math.floor(pixelY / lineHeight)));

    // Measure to find character position
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d')!;
    const fontStyle = shape.fontStyle === 'italic' ? 'italic ' : '';
    const fontWeight = shape.fontWeight === 'bold' ? 'bold ' : '';
    ctx.font = `${fontStyle}${fontWeight}${TEXT_BASE_FONT_SIZE}px ${shape.fontFamily}`;

    const line = lines[lineIndex];
    const fullLineWidth = ctx.measureText(line).width;

    // Calculate line start X based on alignment
    let lineStartX: number;
    switch (shape.textAlign) {
      case 'center':
        lineStartX = (baseWidthPx - fullLineWidth) / 2;
        break;
      case 'right':
        lineStartX = baseWidthPx - fullLineWidth;
        break;
      default:
        lineStartX = 0;
    }

    // Find character at X position
    const clickXInLine = pixelX - lineStartX;
    let charIndex = 0;
    let prevWidth = 0;

    for (let i = 0; i <= line.length; i++) {
      const width = ctx.measureText(line.substring(0, i)).width;
      if (width > clickXInLine) {
        // Check if click is closer to this char or previous
        if (clickXInLine - prevWidth < width - clickXInLine) {
          charIndex = i - 1;
        } else {
          charIndex = i;
        }
        break;
      }
      prevWidth = width;
      charIndex = i;
    }

    // Convert to absolute index in full text
    let absoluteIndex = 0;
    for (let i = 0; i < lineIndex; i++) {
      absoluteIndex += lines[i].length + 1; // +1 for newline
    }
    absoluteIndex += Math.max(0, Math.min(line.length, charIndex));

    return absoluteIndex;
  }

  // Cleanup on unmount
  onUnmounted(() => {
    stopBlinking();
  });

  return {
    editState,
    startEditing,
    stopEditing,
    handleKeyDown,
    handleClick,
    handleDoubleClick,
    getEditingShape,
  };
}
