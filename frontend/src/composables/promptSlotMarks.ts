/**
 * How each slot in the prompt editor shows what is chosen for it (CodeMirror side).
 *
 * The host hands over one look per slot (`setSlotMarks`): a tint while it varies, a slow sheen
 * while its variants are being written, a single dot once something is chosen, the image's
 * thumbnail when kept from one (Keep from this), no tint as written, struck through when left
 * out. The text says *that* a slot is set; the lines under the prompt say *what*.
 *
 * Slots are matched to their looks by place and words, so a slot just typed (not in the
 * prepared program yet) takes the fallback look. With no marks set, slots keep the editor's
 * plain slot look. Hovering a slot and clicking its glyph are reported to the host.
 */
import { Decoration, EditorView, ViewPlugin, WidgetType, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { StateEffect, StateField, type Extension } from '@codemirror/state'
import { findSlots } from '../utils/promptSyntax'
import type { SlotLookKind } from '../utils/programChoices'

export type SlotGlyph = { kind: 'dot' } | { kind: 'thumb'; src: string | null }

export interface SlotLook {
  /** Its 1-based place among the prompt's slots. */
  n: number
  words: string
  kind: SlotLookKind
  glyph: SlotGlyph | null
}

export interface SlotMarks {
  looks: SlotLook[]
  /** The look of a slot that has none (just typed). */
  fallback: SlotLookKind
}

export const setSlotMarks = StateEffect.define<SlotMarks | null>()

export const slotMarksField = StateField.define<SlotMarks | null>({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setSlotMarks)) value = e.value
    return value
  },
})

class Glyph extends WidgetType {
  constructor(readonly n: number, readonly glyph: SlotGlyph) { super() }
  eq(o: Glyph) { return o.n === this.n && JSON.stringify(o.glyph) === JSON.stringify(this.glyph) }
  toDOM() {
    const el = document.createElement('span')
    el.className = `cm-slot-glyph cm-slot-glyph-${this.glyph.kind}`
    el.dataset.slotGlyph = String(this.n)
    el.setAttribute('aria-hidden', 'true')
    if (this.glyph.kind === 'thumb' && this.glyph.src) el.style.backgroundImage = `url("${this.glyph.src.replace(/"/g, '%22')}")`
    return el
  }
  ignoreEvent() { return false }
}

/** The look for the slot at place `n` with these words. */
export function lookFor(marks: SlotMarks, n: number, words: string): SlotLook {
  const exact = marks.looks.find(l => l.n === n && l.words === words)
  if (exact) return exact
  const same = marks.looks.filter(l => l.words === words)
  return same.length === 1 ? { ...same[0], n } : { n, words, kind: marks.fallback, glyph: null }
}

function build(text: string, marks: SlotMarks | null): DecorationSet {
  if (!marks) return Decoration.none
  const ranges = []
  for (const [i, [from, to]] of findSlots(text).entries()) {
    const n = i + 1
    const look = lookFor(marks, n, text.slice(from + 1, to - 1))
    ranges.push(Decoration.mark({ class: `cm-slot-mark cm-slot-${look.kind}`, attributes: { 'data-slot-n': String(n), 'data-slot-look': look.kind } }).range(from, to))
    if (look.glyph) ranges.push(Decoration.widget({ widget: new Glyph(n, look.glyph), side: 1 }).range(to))
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
  // Chosen (one, several, seeds, kept from an image): filled.
  '.cm-slot-pinned, .cm-slot-several, .cm-slot-keep': {
    color: 'rgb(var(--color-text-primary-rgb))',
    backgroundColor: 'rgb(var(--color-selection-rgb) / 0.32)',
    boxShadow: '0 0 0 1px rgb(var(--color-selection-rgb) / 0.6)',
  },
  '.cm-slot-pinned:hover, .cm-slot-several:hover, .cm-slot-keep:hover': { backgroundColor: 'rgb(var(--color-selection-rgb) / 0.42)' },
  // As written: the words go in as they are; no tint, a quiet outline keeps it a slot.
  '.cm-slot-written': { boxShadow: '0 0 0 1px rgb(var(--color-text-muted-rgb) / 0.45)' },
  '.cm-slot-written:hover': { backgroundColor: 'rgb(var(--color-text-muted-rgb) / 0.12)' },
  // Left out: struck through.
  '.cm-slot-off': {
    color: 'rgb(var(--color-text-muted-rgb))',
    textDecoration: 'line-through rgb(var(--color-text-muted-rgb) / 0.8)',
  },
  '.cm-slot-off:hover': { backgroundColor: 'rgb(var(--color-text-muted-rgb) / 0.12)' },
  '.cm-slot-glyph': { display: 'inline-block', marginLeft: '3px', cursor: 'pointer' },
  '.cm-slot-glyph-dot': { width: '6px', height: '6px', borderRadius: '9999px', background: 'rgb(var(--color-selection-rgb))', verticalAlign: '2px' },
  '.cm-slot-glyph-thumb': {
    width: '12px', height: '15px', borderRadius: '3px', verticalAlign: '-3px',
    backgroundColor: 'rgb(var(--color-selection-rgb) / 0.3)', backgroundSize: 'cover', backgroundPosition: 'center',
    boxShadow: '0 0 0 1px rgb(var(--color-selection-rgb) / 0.9)',
  },
  '.cm-slot-glyph:hover': { filter: 'brightness(1.2)' },
})

export interface SlotMarkHandlers {
  /** The pointer moved onto a slot (its place and where it is), or off every slot (null). */
  onHover: (n: number | null, rect: DOMRect | null) => void
  /** A slot's glyph was clicked. */
  onGlyph: (n: number) => void
}

export function slotMarks(h: SlotMarkHandlers): Extension {
  const plugin = ViewPlugin.fromClass(class {
    decorations: DecorationSet
    over: number | null = null
    constructor(view: EditorView) { this.decorations = build(view.state.doc.toString(), view.state.field(slotMarksField)) }
    update(u: ViewUpdate) {
      const was = u.startState.field(slotMarksField)
      const now = u.state.field(slotMarksField)
      if (u.docChanged || was !== now) this.decorations = build(u.state.doc.toString(), now)
    }
  }, {
    decorations: v => v.decorations,
    eventHandlers: {
      mouseover(e) {
        const el = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-slot-n]') : null
        const n = el ? Number(el.dataset.slotN) : null
        if (n === this.over) return
        this.over = n
        h.onHover(n, el ? el.getBoundingClientRect() : null)
      },
      mouseleave() { this.over = null; h.onHover(null, null) },
      mousedown(e) {
        const g = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-slot-glyph]') : null
        if (!g) return false
        e.preventDefault()
        h.onGlyph(Number(g.dataset.slotGlyph))
        return true
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
