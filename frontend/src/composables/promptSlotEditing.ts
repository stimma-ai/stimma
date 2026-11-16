/**
 * Making and opening slots in the prompt editor (CodeMirror side).
 *
 * - Phrases Suggest says could vary carry a dotted underline (`varyField`).
 * - With words selected, typing `<` puts the brackets around them, where the grammar
 *   allows a slot there (`slotWrapRange`). Otherwise `<` types as usual.
 * - Clicking a slot, or an underlined phrase, and settling a selection are reported to
 *   the editor component, which offers Add Detail and Add Variety or opens the slot.
 * - The caret leaving the slot just edited (typing past it, or moving away) is reported, so
 *   Fluent reads that slot without waiting for a pause.
 */
import { EditorView, Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from '@codemirror/view'
import { StateEffect, StateField, RangeSetBuilder, type Extension } from '@codemirror/state'
import { isolateHistory } from '@codemirror/commands'
import { findSlots, slotWrapRange, usableVaryPhrases } from '../utils/promptSyntax'

/** A phrase Suggest underlined: its kind ("hairstyle"), which way Suggest would take it
    (Add Detail or Add Variety), `mode` 'one' when it names one specific thing, and the
    `label` its chip shows. */
export interface VaryPhrase { from: number; to: number; text: string; kind?: string; way?: 'detail' | 'any'; mode?: 'one' | 'kind'; label?: string }

/** Replace the underlined phrases (offsets into the current document). */
export const setVaryEffect = StateEffect.define<VaryPhrase[]>()

const varyMark = Decoration.mark({ class: 'cm-could-vary' })

/** The underlined phrases: kept through edits while their words stand as they were. */
const varyField = StateField.define<VaryPhrase[]>({
  create: () => [],
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setVaryEffect)) value = e.value
    if (!tr.docChanged || !value.length) return value
    const text = tr.newDoc.toString()
    const mapped = value.map(p => ({ ...p, from: tr.changes.mapPos(p.from, 1), to: tr.changes.mapPos(p.to, -1) }))
    return usableVaryPhrases(text, mapped)
  },
  provide: f => EditorView.decorations.from(f, (phrases): DecorationSet => {
    const b = new RangeSetBuilder<Decoration>()
    for (const p of phrases) b.add(p.from, p.to, varyMark)
    return b.finish()
  }),
})

/** A slot Suggest would write in: `text` (holding `<words>`) goes in at `at`. */
export interface AddAt { key: string; label: string; at: number; text: string }

/** Replace the slots Suggest would write in (offsets into the current document). */
export const setAddsEffect = StateEffect.define<AddAt[]>()

/** The slot words of an add's text: "face" in " with <face>". */
const addWords = (a: AddAt) => /<([^<>]+)>/.exec(a.text)?.[1]?.trim().toLowerCase() ?? ''

/** Of `adds`, those that still fit the text: their place outside any slot, and no slot of
    their words in it yet. */
export function usableAdds<T extends AddAt>(text: string, adds: readonly T[]): T[] {
  const slots = findSlots(text)
  const have = new Set(slots.map(([a, b]) => text.slice(a + 1, b - 1).trim().toLowerCase()))
  return adds.filter(a => a.at >= 0 && a.at <= text.length && !have.has(addWords(a))
    && !slots.some(([f, t]) => a.at > f && a.at < t))
}

/** The slots Suggest would write in, carried through edits like the underlines. */
export const addsField = StateField.define<AddAt[]>({
  create: () => [],
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setAddsEffect)) value = e.value
    if (!tr.docChanged || !value.length) return value
    return usableAdds(tr.newDoc.toString(), value.map(a => ({ ...a, at: tr.changes.mapPos(a.at, 1) })))
  },
})

/** What the editor shows now: the underlined phrases and the adds, as edits have moved them. */
export function shownSuggestions(view: EditorView): { phrases: VaryPhrase[]; adds: AddAt[] } {
  return { phrases: view.state.field(varyField, false) ?? [], adds: view.state.field(addsField, false) ?? [] }
}

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

/** Write `<words>` in place of [from, to) as one undo step (Add Variety: `<hairstyle>` over "short bob");
    where the slot starts, or null when no slot could stand there. */
export function replaceWithSlot(view: EditorView, from: number, to: number, words: string): number | null {
  if (!slotWrapRange(view.state.doc.toString(), from, to)) return null
  const insert = `<${words}>`
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + insert.length },
    userEvent: 'input.slot',
    annotations: isolateHistory.of('full'),
  })
  return from
}

/** Write `words` as the words of the slot spanning [from, to) (brackets included), as one undo
    step (Add Variety on a slot: `<short bob>` becomes `<hairstyle>`); where the slot starts, or
    null when [from, to) isn't a slot. */
export function rewriteSlot(view: EditorView, from: number, to: number, words: string): number | null {
  const doc = view.state.doc
  if (doc.sliceString(from, from + 1) !== '<' || doc.sliceString(to - 1, to) !== '>' || !words.trim()) return null
  view.dispatch({
    changes: { from: from + 1, to: to - 1, insert: words },
    selection: { anchor: from + words.length + 2 },
    userEvent: 'input.slot',
    annotations: isolateHistory.of('full'),
  })
  return from
}

/** Take the brackets off the slot spanning [from, to) (brackets included), its words staying,
    as one undo step. */
export function unwrapSlot(view: EditorView, from: number, to: number) {
  const doc = view.state.doc
  if (doc.sliceString(from, from + 1) !== '<' || doc.sliceString(to - 1, to) !== '>') return
  view.dispatch({
    changes: [{ from, to: from + 1 }, { from: to - 1, to }],
    userEvent: 'delete.slot',
    annotations: isolateHistory.of('full'),
  })
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

/** [from, to) grown to whole words: a drag rarely starts or ends right at a word's edge, and a
    slot can't start or end inside one (`w<oman>` isn't a slot). */
export function wholeWords(text: string, from: number, to: number): [number, number] {
  if (from > to) [from, to] = [to, from]
  const word = (i: number) => i >= 0 && i < text.length && /[\p{L}\p{N}_]/u.test(text[i])
  while (word(from - 1) && word(from)) from--
  while (word(to - 1) && word(to)) to++
  return [from, to]
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
    addsField,
    // With words selected, `<` wraps them, as a quote key wraps a selection in a code editor.
    EditorView.inputHandler.of((view, from, to, text) => {
      if (text !== '<' || from === to || !h.enabled() || view.state.selection.ranges.length > 1) return false
      const at = wrapSlot(view, from, to)
      if (at == null) return false
      h.onWrapped(at)
      return true
    }),
    EditorView.domEventHandlers({
      // A drag that starts in the words can end anywhere: under the last line (the box is
      // taller than its text), past its edge, off the window. So the release is heard on the
      // whole page, not just the text; heard only on the text, a missed release left every
      // later selection unreported.
      mousedown(e, view) {
        if (e.button !== 0 || pointerDown) return
        pointerDown = true
        const win = view.dom.ownerDocument.defaultView ?? window
        const up = () => {
          win.removeEventListener('mouseup', up, true)
          win.removeEventListener('blur', up)
          pointerDown = false
          report(view)
        }
        win.addEventListener('mouseup', up, true)
        win.addEventListener('blur', up)
      },
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
