import { layer, RectangleMarker, Direction, type EditorView, type LayerMarker } from '@codemirror/view'
import type { Extension } from '@codemirror/state'

// Robust selection-background layer for WebKit / WKWebView (Tauri on macOS).
//
// CodeMirror's built-in drawSelection measures selection geometry with
// Range.getClientRects (coordsAtPos with the ±2 "kludge" side, per text span).
// On WebKit that intermittently returns a rect one visual row too tall for the
// first row of a wrapped-line selection, so the full-width "between" fill
// starts a row late and the second row loses its left segment — the visible
// gap. The WebKit getClientRects bug is long-standing (bugs.webkit.org #103658,
// #46203) and can't be relied on to be fixed: WKWebView uses the system WebKit,
// so users get whatever their macOS ships.
//
// This layer rebuilds the rectangles from only single-position coordsAtPos
// queries — which WebKit returns at the correct one-row height — plus the
// content-box edges. It never does a multi-char range measurement. Handles a
// contiguous LTR stream selection (first partial row, full-width middle, last
// partial row); bails on RTL/bidi.

function baseOffset(view: EditorView) {
  const rect = view.scrollDOM.getBoundingClientRect()
  const left =
    view.textDirection === Direction.LTR
      ? rect.left
      : rect.right - view.scrollDOM.clientWidth * view.scaleX
  return {
    left: left - view.scrollDOM.scrollLeft * view.scaleX,
    top: rect.top - view.scrollDOM.scrollTop * view.scaleY,
  }
}

function selectionMarkers(view: EditorView): readonly LayerMarker[] {
  // Only left-to-right text; bidi/RTL falls through to nothing here.
  if (view.textDirection !== Direction.LTR) return []

  const markers: RectangleMarker[] = []
  const base = baseOffset(view)

  const contentRect = view.contentDOM.getBoundingClientRect()
  const lineElt = view.contentDOM.querySelector('.cm-line')
  const lineStyle = lineElt ? window.getComputedStyle(lineElt) : null
  const leftSide =
    contentRect.left +
    (lineStyle ? parseInt(lineStyle.paddingLeft) + Math.min(0, parseInt(lineStyle.textIndent) || 0) : 0)
  const rightSide = contentRect.right - (lineStyle ? parseInt(lineStyle.paddingRight) : 0)

  const lh = view.defaultLineHeight

  const push = (left: number, top: number, right: number, bottom: number) => {
    markers.push(
      new RectangleMarker(
        'cm-wkSelectionBackground',
        left - base.left,
        top - base.top,
        Math.max(0, right - left),
        bottom - top,
      ),
    )
  }

  for (const range of view.state.selection.ranges) {
    if (range.empty) continue
    // Clip to the rendered viewport so we never measure off-screen positions.
    const from = Math.max(range.from, view.viewport.from)
    const to = Math.min(range.to, view.viewport.to)
    if (from >= to) continue

    // Single-position coords are returned at the correct one-row height on
    // WebKit; the multi-char range query is the one that comes back too tall.
    const start = view.coordsAtPos(from, 1)
    const end = view.coordsAtPos(to, -1)
    if (!start || !end) continue

    const sameRow = Math.abs(start.top - end.top) < lh / 2
    if (sameRow) {
      push(start.left, start.top, end.right, end.bottom)
    } else {
      // First visual row: selection start → right edge.
      push(start.left, start.top, rightSide, start.bottom)
      // Middle: full-width block spanning every row between the partial ends.
      if (end.top - start.bottom > 1) {
        push(leftSide, start.bottom, rightSide, end.top)
      }
      // Last visual row: left edge → selection end.
      push(leftSide, end.top, end.right, end.bottom)
    }
  }

  return markers
}

// A drawn selection-background layer that replaces drawSelection's buggy one.
// Pair it with hiding the built-in `.cm-selectionLayer` and styling
// `.cm-wkSelectionBackground` in the editor theme.
export function webkitSelectionLayer(): Extension {
  return layer({
    above: false,
    class: 'cm-wkSelectionLayer',
    update(update) {
      return (
        update.docChanged ||
        update.selectionSet ||
        update.viewportChanged ||
        update.geometryChanged
      )
    },
    markers: selectionMarkers,
  })
}
