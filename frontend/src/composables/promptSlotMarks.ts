/**
 * How each slot in the prompt editor shows what is chosen for it (CodeMirror side), matching
 * its row under the prompt: the slot tint while it varies, a stronger fill once limited, plain
 * text when it can't vary, a shimmer while its first variants are written.
 *
 * Slots are matched to their looks by place and words, so a slot just typed (not in the
 * prepared program yet) takes the fallback look. While the user is typing, the slot at the
 * caret never shows as being written: nothing reads it until they pause or leave it. With no
 * marks set, slots keep the editor's plain slot look.
 *
 * The user's own `{a|b}` lists keep their list color until something is chosen for them, then
 * take the limited fill. Clicking a list is reported to the host, which opens its row.
 */
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { StateEffect, StateField, type Extension } from '@codemirror/state'
import { findLists, findSlots } from '../utils/promptSyntax'
import type { SlotLookKind } from '../utils/programChoices'

export interface SlotLook {
  /** Its 1-based place among the prompt's slots. */
  n: number
  words: string
  kind: SlotLookKind
}

/** A list of the user's own that has something chosen: matched by its place and options. */
export interface ListLook {
  n: number
  items: string[]
  kind: SlotLookKind
}

export interface SlotMarks {
  looks: SlotLook[]
  lists?: ListLook[]
  /** The look of a slot that has none (just typed). */
  fallback: SlotLookKind
  /** The user is typing: the slot at the caret (in it or right at its edge) looks plain. */
  typing?: boolean
}

export const setSlotMarks = StateEffect.define<SlotMarks | null>()

const slotMarksField = StateField.define<SlotMarks | null>({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setSlotMarks)) value = e.value
    return value
  },
})

/** The look for the slot at place `n` with these words. */
function lookFor(marks: SlotMarks, n: number, words: string): SlotLook {
  const exact = marks.looks.find(l => l.n === n && l.words === words)
  if (exact) return exact
  const same = marks.looks.filter(l => l.words === words)
  return same.length === 1 ? { ...same[0], n } : { n, words, kind: marks.fallback }
}

function build(text: string, marks: SlotMarks | null, caret: number): DecorationSet {
  if (!marks) return Decoration.none
  const ranges = []
  for (const [i, [from, to]] of findSlots(text).entries()) {
    const n = i + 1
    let look = lookFor(marks, n, text.slice(from + 1, to - 1))
    if (marks.typing && look.kind === 'writing' && caret >= from && caret <= to) look = { ...look, kind: 'varying' }
    ranges.push(Decoration.mark({ class: `cm-slot-mark cm-slot-${look.kind}`, attributes: { 'data-slot-n': String(n), 'data-slot-look': look.kind } }).range(from, to))
  }
  // Every list is marked, so a click finds it; only one with something chosen looks set.
  for (const [i, { from, to, items }] of findLists(text).entries()) {
    const n = i + 1
    const look = marks.lists?.find(l => l.n === n && JSON.stringify(l.items) === JSON.stringify(items))
    const set = look && look.kind !== 'varying' ? look : null
    ranges.push(Decoration.mark({
      class: `cm-list-mark${set ? ` cm-list-set cm-slot-${set.kind}` : ''}`,
      attributes: { 'data-list-n': String(n), 'data-list-look': set?.kind || 'varying' },
    }).range(from, to))
  }
  return Decoration.set(ranges, true)
}

const theme = EditorView.baseTheme({
  // With marks, each look replaces the plain slot tint.
  '&.cm-slot-marks .cm-slot': { color: 'inherit', backgroundColor: 'transparent', boxShadow: 'none' },
  '.cm-slot-mark': { borderRadius: '3px', cursor: 'pointer', transition: 'background-color 120ms, box-shadow 120ms' },
  '.cm-slot-varying': {
    color: 'rgb(var(--color-selection-rgb))',
    backgroundColor: 'rgb(var(--color-selection-rgb) / 0.12)',
    boxShadow: '0 0 0 1px rgb(var(--color-selection-rgb) / 0.25)',
  },
  '.cm-slot-varying:hover': { backgroundColor: 'rgb(var(--color-selection-rgb) / 0.2)' },
  // Still being written: a slow sheen runs through it. It reads as clickable, which it is.
  '.cm-slot-writing': {
    color: 'rgb(var(--color-selection-rgb) / 0.7)',
    backgroundColor: 'rgb(var(--color-selection-rgb) / 0.05)',
    backgroundImage: 'linear-gradient(100deg, transparent 20%, rgb(var(--color-selection-rgb) / 0.28) 50%, transparent 80%)',
    backgroundSize: '220% 100%',
    animation: 'cm-slot-sheen 1.6s linear infinite',
    outline: '1px dashed rgb(var(--color-selection-rgb) / 0.55)',
  },
  '@keyframes cm-slot-sheen': { from: { backgroundPosition: '120% 0' }, to: { backgroundPosition: '-120% 0' } },
  // Limited to some variants or seeds: a stronger fill.
  '.cm-slot-restricted': {
    color: 'rgb(var(--color-text-primary-rgb))',
    backgroundColor: 'rgb(var(--color-selection-rgb) / 0.3)',
    boxShadow: '0 0 0 1px rgb(var(--color-selection-rgb) / 0.55)',
  },
  '.cm-slot-restricted:hover': { backgroundColor: 'rgb(var(--color-selection-rgb) / 0.4)' },
  // Can't vary (it goes in as its words): plain text, still a slot to click.
  '.cm-slot-words': { color: 'rgb(var(--color-text-primary-rgb))' },
  '.cm-slot-words:hover': { backgroundColor: 'rgb(var(--color-text-muted-rgb) / 0.12)' },
  '.cm-list-mark': { cursor: 'pointer' },
  // A list with something chosen takes the slot marks over its own list color.
  '.cm-list-set': { borderRadius: '3px' },
  '.cm-list-set .cm-wildcard': { color: 'inherit', backgroundColor: 'transparent' },
})

export interface SlotMarkHandlers {
  /** A list of the user's own (its place among the lists) was clicked. */
  onList: (n: number, rect: DOMRect) => void
}

export function slotMarks(h: SlotMarkHandlers): Extension {
  const plugin = ViewPlugin.fromClass(class {
    decorations: DecorationSet
    constructor(view: EditorView) { this.decorations = build(view.state.doc.toString(), view.state.field(slotMarksField), view.state.selection.main.head) }
    update(u: ViewUpdate) {
      const was = u.startState.field(slotMarksField)
      const now = u.state.field(slotMarksField)
      if (u.docChanged || was !== now || (now?.typing && u.selectionSet)) this.decorations = build(u.state.doc.toString(), now, u.state.selection.main.head)
    }
  }, {
    decorations: v => v.decorations,
    eventHandlers: {
      click(e, view) {
        if (!view.state.selection.main.empty) return false
        const list = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-list-n]') : null
        if (list) h.onList(Number(list.dataset.listN), list.getBoundingClientRect())
        return false
      },
    },
  })
  return [
    slotMarksField,
    plugin,
    theme,
    EditorView.editorAttributes.compute([slotMarksField], s => (s.field(slotMarksField) ? { class: 'cm-slot-marks' } : {})),
  ]
}
