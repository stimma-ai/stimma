/**
 * Making and opening slots in the prompt editor (CodeMirror side).
 *
 * - Phrases Suggest says could vary carry a dotted underline (`varyField`).
 * - With words selected, typing `<` puts the brackets around them, where the grammar
 *   allows a slot there (`slotWrapRange`). Otherwise `<` types as usual.
 * - Clicking a slot, or an underlined phrase, and settling a selection are reported to
 *   the editor component, which shows "Vary this" or opens the slot.
 * - The caret leaving the slot just edited (typing past it, or moving away) is reported, so
 *   Fluent reads that slot without waiting for a pause.
 */
import { EditorView, Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from '@codemirror/view'
import { StateEffect, StateField, RangeSetBuilder, type Extension } from '@codemirror/state'
import { isolateHistory } from '@codemirror/commands'
import { findSlots, slotWrapRange, usableVaryPhrases } from '../utils/promptSyntax'

export interface VaryPhrase { from: number; to: number; text: string }

/** Replace the underlined phrases (offsets into the current document). */
export const setVaryEffect = StateEffect.define<VaryPhrase[]>()

const varyMark = Decoration.mark({ class: 'cm-could-vary' })

/** The underlined phrases: kept through edits while their words stand as they were. */
export const varyField = StateField.define<VaryPhrase[]>({
  create: () => [],
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setVaryEffect)) value = e.value
    if (!tr.docChanged || !value.length) return value
    const text = tr.newDoc.toString()
    const mapped = value.map(p => ({ from: tr.changes.mapPos(p.from, 1), to: tr.changes.mapPos(p.to, -1), text: p.text }))
    return usableVaryPhrases(text, mapped)
  },
  provide: f => EditorView.decorations.from(f, (phrases): DecorationSet => {
    const b = new RangeSetBuilder<Decoration>()
    for (const p of phrases) b.add(p.from, p.to, varyMark)
    return b.finish()
  }),
})

export interface SlotEditingHandlers {
  /** Whether slots can be made and opened here (Fluent, not Direct or Raw). */
  enabled: () => boolean
  /** A slot was clicked; `pos` is inside it. */
  onSlotClick: (pos: number) => void
  /** An underlined phrase was clicked. */
  onPhraseClick: (phrase: VaryPhrase) => void
  /** The selection settled (from === to when it is just the cursor). */
  onSelection: (range: { from: number; to: number }) => void
  /** `<` made a slot; `from` is its opening bracket. */
  onWrapped: (from: number) => void
  /** The text changed or scrolled: anything floating over it is out of place. */
  onMoved: () => void
  /** The caret left the slot the last edit was in or right at. */
  onLeftSlot?: () => void
}

/** Put the brackets around [from, to) as one undo step. Returns the `<`'s position, or null. */
export function wrapSlot(view: EditorView, from: number, to: number): number | null {
  const at = slotWrapRange(view.state.doc.toString(), from, to)
  if (!at) return null
  const [a, b] = at
  view.dispatch({
    changes: [{ from: a, insert: '<' }, { from: b, insert: '>' }],
    selection: { anchor: b + 2 },
    userEvent: 'input.slot',
    annotations: isolateHistory.of('full'),
  })
  return a
}

/** Replace the whole text with `text` as one undo step, changing only what differs. */
export function replaceDocument(view: EditorView, text: string) {
  const old = view.state.doc.toString()
  if (old === text) return
  let start = 0
  while (start < old.length && start < text.length && old[start] === text[start]) start++
  let end = 0
  while (end < old.length - start && end < text.length - start && old[old.length - 1 - end] === text[text.length - 1 - end]) end++
  view.dispatch({
    changes: { from: start, to: old.length - end, insert: text.slice(start, text.length - end) },
    userEvent: 'input.slot',
    annotations: isolateHistory.of('full'),
  })
}

/** Where [from, to) is on screen (the box around it when it wraps), or null when hidden. */
export function rangeRect(view: EditorView, from: number, to: number): DOMRect | null {
  const a = view.coordsAtPos(from, 1)
  const b = view.coordsAtPos(to, -1)
  if (!a || !b) return null
  if (Math.abs(a.top - b.top) < 2) return new DOMRect(a.left, a.top, Math.max(b.right - a.left, 1), a.bottom - a.top)
  const left = Math.min(a.left, b.left)
  const right = Math.max(a.right, b.right, view.contentDOM.getBoundingClientRect().right - 12)
  return new DOMRect(left, a.top, right - left, b.bottom - a.top)
}

export function slotEditing(h: SlotEditingHandlers): Extension {
  let pointerDown = false
  let settle: ReturnType<typeof setTimeout> | null = null
  const report = (view: EditorView) => {
    if (settle) clearTimeout(settle)
    settle = setTimeout(() => {
      settle = null
      if (pointerDown || !h.enabled()) return
      const sel = view.state.selection.main
      h.onSelection({ from: sel.from, to: sel.to })
    }, 120)
  }
  // The slot the last edit was in or right at, while the caret stays there.
  let edited: [number, number] | null = null
  return [
    varyField,
    // With words selected, `<` wraps them, as a quote key wraps a selection in a code editor.
    EditorView.inputHandler.of((view, from, to, text) => {
      if (text !== '<' || from === to || !h.enabled() || view.state.selection.ranges.length > 1) return false
      const at = wrapSlot(view, from, to)
      if (at == null) return false
      h.onWrapped(at)
      return true
    }),
    EditorView.domEventHandlers({
      mousedown() { pointerDown = true },
      mouseup(_e, view) { pointerDown = false; report(view) },
      scroll() { h.onMoved() },
      click(e, view) {
        if (!h.enabled() || !view.state.selection.main.empty) return false
        const el = e.target instanceof Element ? e.target : null
        const slotEl = el?.closest('.cm-slot')
        if (slotEl) {
          h.onSlotClick(view.posAtDOM(slotEl, 0))
          return false
        }
        if (el?.closest('.cm-could-vary')) {
          const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
          const phrase = pos == null ? null : view.state.field(varyField).find(p => pos >= p.from && pos <= p.to)
          if (phrase) h.onPhraseClick(phrase)
        }
        return false
      },
    }),
    ViewPlugin.fromClass(class {
      update(u: ViewUpdate) {
        if (u.docChanged || u.geometryChanged) h.onMoved()
        if (u.selectionSet) report(u.view)
        if (!u.docChanged && !u.selectionSet) return
        const head = u.state.selection.main.head
        const was = edited && [u.changes.mapPos(edited[0], 1), u.changes.mapPos(edited[1], -1)]
        let left = false
        if (u.docChanged) {
          // Typed past it: it's still there, whole. Not when an edit broke it (a backspace
          // over its `>` on the way to retyping its words).
          const spans = findSlots(u.state.doc.toString())
          edited = spans.find(([from, to]) => head >= from && head <= to) ?? null
          left = !!was && !edited && spans.some(([from, to]) => from === was[0] && to === was[1])
        } else if (was && (head < was[0] || head > was[1])) {
          edited = null
          left = true
        }
        if (left && h.enabled()) h.onLeftSlot?.()
      }
    }),
  ]
}
