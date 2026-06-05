<template>
  <div class="w-full h-full flex flex-col bg-base overflow-hidden relative">
    <div ref="mountEl" class="flex-1 min-h-0 overflow-hidden" />
    <div v-if="loading && !code" class="absolute inset-0 flex items-center justify-center text-content-muted text-sm bg-base">
      Loading…
    </div>
    <div v-else-if="loading" class="pointer-events-none absolute right-3 top-3 rounded border border-edge-subtle bg-surface/90 px-2 py-1 text-[11px] text-content-muted shadow-sm">
      Refreshing…
    </div>

    <!-- Slot for content between the editor and the action bar (e.g. errors panel) -->
    <slot name="below-editor" />

    <!-- Bottom Action Bar -->
    <div v-if="code" class="px-3 py-1.5 flex items-center justify-end gap-1.5 bg-surface border-t border-edge-subtle">
      <button
        @click="toggleVim"
        :class="[
          'text-[10px] font-mono font-medium px-1.5 py-0.5 rounded transition-colors',
          vimEnabled
            ? 'text-green-500 bg-green-500/10'
            : 'text-content-muted hover:text-content-secondary'
        ]"
        :title="vimEnabled ? 'Switch to regular keybindings' : 'Switch to Vim keybindings'"
      >
        {{ vimEnabled ? 'VIM' : 'STD' }}
      </button>

      <button
        @click="toggleMonospace"
        :class="[
          'text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors',
          monospaceEnabled
            ? 'text-blue-500 bg-blue-500/10 font-mono'
            : 'text-content-muted hover:text-content-secondary'
        ]"
        :title="monospaceEnabled ? 'Switch to proportional font' : 'Switch to monospace font'"
      >
        {{ monospaceEnabled ? 'MONO' : 'SANS' }}
      </button>

      <button
        @click="copyCode"
        :class="[
          'flex items-center justify-center px-1.5 py-0.5 rounded transition-colors',
          copied
            ? 'text-green-500 bg-green-500/10'
            : 'text-content-muted hover:text-content-secondary'
        ]"
        :title="copied ? 'Copied' : 'Copy code'"
        :aria-label="copied ? 'Copied' : 'Copy code'"
      >
        <svg v-if="copied" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 8.25V6a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 6v8.25A2.25 2.25 0 0 0 6 16.5h2.25m8.25-8.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-7.5A2.25 2.25 0 0 1 8.25 18v-1.5m8.25-8.25h-6a2.25 2.25 0 0 0-2.25 2.25v6" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useTheme } from '../../composables/useTheme'
import {
  EditorView,
  keymap,
  drawSelection,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter,
  Decoration,
  type DecorationSet,
  gutter,
  GutterMarker,
} from '@codemirror/view'
import { Compartment, EditorState, StateEffect, StateField, RangeSetBuilder, RangeSet } from '@codemirror/state'
import { python } from '@codemirror/lang-python'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { defaultKeymap, historyKeymap, history } from '@codemirror/commands'
import { search, searchKeymap } from '@codemirror/search'
import { registerVimSaveHandler, useVimToggle, vimPanelKeydownHandler } from '../../composables/codeMirrorVim'
import { webkitSelectionLayer } from '../../composables/webkitSelectionLayer'

const MONO_KEY = 'stimma:recipe-code-monospace'

const props = withDefaults(defineProps<{
  code: string
  baselineCode?: string
  loading: boolean
  editing?: boolean
  errorLines?: number[]
}>(), { baselineCode: '', editing: true, errorLines: () => [] })

const emit = defineEmits<{
  (e: 'update:dirty', value: boolean): void
  (e: 'update:code', value: string): void
  (e: 'save-request'): void
}>()

const mountEl = ref<HTMLElement | null>(null)
const copied = ref(false)
const dirty = ref(false)
let view: EditorView | null = null
let copiedTimer: ReturnType<typeof setTimeout> | null = null
let unregisterVimSaveHandler: (() => void) | null = null
let serverBaseline = ''

const { vimEnabled, vimCompartment, getVimExtension, toggleVim, bindView } = useVimToggle()

const readOnlyCompartment = new Compartment()
const fontCompartment = new Compartment()
const highlightCompartment = new Compartment()
const monospaceEnabled = ref(localStorage.getItem(MONO_KEY) !== 'false')

const { resolvedTheme } = useTheme()

// --- Error decorations ---
// Drives both the inline line-background highlight and the gutter marker.
// Lines are 1-indexed (CodeMirror Line numbers).
const setErrorLinesEffect = StateEffect.define<number[]>()

const errorLineDeco = Decoration.line({ class: 'cm-error-line' })

class ErrorGutterMarker extends GutterMarker {
  toDOM() {
    const el = document.createElement('div')
    el.className = 'cm-error-gutter-marker'
    el.title = 'Error on this line'
    el.textContent = '●'
    return el
  }
}
const errorGutterMarker = new ErrorGutterMarker()

const errorLinesField = StateField.define<{ lines: Set<number>; deco: DecorationSet }>({
  create() {
    return { lines: new Set<number>(), deco: Decoration.none }
  },
  update(value, tr) {
    let next = value
    for (const effect of tr.effects) {
      if (effect.is(setErrorLinesEffect)) {
        const lines = new Set<number>(effect.value.filter((n) => n > 0))
        const builder = new RangeSetBuilder<Decoration>()
        const sorted = [...lines].sort((a, b) => a - b)
        const docLines = tr.state.doc.lines
        for (const ln of sorted) {
          if (ln < 1 || ln > docLines) continue
          const line = tr.state.doc.line(ln)
          builder.add(line.from, line.from, errorLineDeco)
        }
        next = { lines, deco: builder.finish() }
      }
    }
    return next
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.deco),
})

const errorGutter = gutter({
  class: 'cm-error-gutter',
  markers(view) {
    const value = view.state.field(errorLinesField, false)
    if (!value || value.lines.size === 0) return RangeSet.empty
    const builder = new RangeSetBuilder<GutterMarker>()
    const sorted = [...value.lines].sort((a, b) => a - b)
    const docLines = view.state.doc.lines
    for (const ln of sorted) {
      if (ln < 1 || ln > docLines) continue
      const line = view.state.doc.line(ln)
      builder.add(line.from, line.from, errorGutterMarker)
    }
    return builder.finish()
  },
  initialSpacer: () => errorGutterMarker,
})

function applyErrorLines() {
  if (!view) return
  view.dispatch({ effects: setErrorLinesEffect.of([...(props.errorLines || [])]) })
}

function scrollToLine(line: number) {
  if (!view || !line || line < 1) return
  const doc = view.state.doc
  if (line > doc.lines) return
  const target = doc.line(line)
  view.dispatch({
    selection: { anchor: target.from },
    effects: EditorView.scrollIntoView(target.from, { y: 'center' }),
  })
  view.focus()
}

function getReadOnlyExtension() {
  return EditorState.readOnly.of(false)
}

function setDirty(v: boolean) {
  if (dirty.value === v) return
  dirty.value = v
  emit('update:dirty', v)
}

function getCurrentCode(): string {
  return view?.state.doc.toString() ?? props.code
}

function revertToOriginal() {
  if (!view) return
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: serverBaseline },
  })
  setDirty(false)
}

const monoFontTheme = EditorView.theme({
  '&': { fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace' },
  '.cm-scroller': { fontFamily: 'inherit' },
})
const sansFontTheme = EditorView.theme({
  '&': { fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
  '.cm-scroller': { fontFamily: 'inherit' },
})

function getFontExtension() {
  return monospaceEnabled.value ? monoFontTheme : sansFontTheme
}

function toggleMonospace() {
  monospaceEnabled.value = !monospaceEnabled.value
  localStorage.setItem(MONO_KEY, String(monospaceEnabled.value))
  view?.dispatch({ effects: fontCompartment.reconfigure(getFontExtension()) })
}

const darkHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: '#6b7d8a', fontStyle: 'italic' },
  { tag: [t.keyword, t.modifier, t.controlKeyword, t.operatorKeyword, t.definitionKeyword], color: '#c792ea' },
  { tag: [t.string, t.special(t.string)], color: '#ecc48d' },
  { tag: [t.number, t.bool, t.null, t.atom], color: '#f78c6c' },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: '#82aaff' },
  { tag: [t.definition(t.variableName), t.definition(t.propertyName)], color: '#d6deeb' },
  { tag: t.variableName, color: '#d6deeb' },
  { tag: t.propertyName, color: '#7fdbca' },
  { tag: [t.className, t.typeName], color: '#ffcb6b' },
  { tag: t.meta, color: '#82aaff' },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: '#89ddff' },
  { tag: t.regexp, color: '#5ca7e4' },
  { tag: t.escape, color: '#f78c6c' },
  { tag: t.invalid, color: '#ff5874' },
])

const lightHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: '#6a737d', fontStyle: 'italic' },
  { tag: [t.keyword, t.modifier, t.controlKeyword, t.operatorKeyword, t.definitionKeyword], color: '#a626a4' },
  { tag: [t.string, t.special(t.string)], color: '#50a14f' },
  { tag: [t.number, t.bool, t.null, t.atom], color: '#986801' },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: '#4078f2' },
  { tag: [t.definition(t.variableName), t.definition(t.propertyName)], color: '#383a42' },
  { tag: t.variableName, color: '#383a42' },
  { tag: t.propertyName, color: '#0184bc' },
  { tag: [t.className, t.typeName], color: '#c18401' },
  { tag: t.meta, color: '#4078f2' },
  { tag: [t.operator, t.punctuation, t.bracket, t.separator], color: '#0184bc' },
  { tag: t.regexp, color: '#0184bc' },
  { tag: t.escape, color: '#986801' },
  { tag: t.invalid, color: '#e45649' },
])

function getHighlightExtension() {
  return syntaxHighlighting(resolvedTheme.value === 'light' ? lightHighlightStyle : darkHighlightStyle)
}

const codeTheme = EditorView.theme({
  '&': { height: '100%', fontSize: '12.5px' },
  '.cm-scroller': { overflow: 'auto', height: '100%' },
  '.cm-content': { caretColor: '#3b82f6', padding: '12px 0' },
  '&.cm-focused': { outline: 'none' },
  '.cm-line': { padding: '0 16px' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#3b82f6', borderLeftWidth: '2px' },
  // CM's own drawn selection background drifts/gaps on WebKit, so hide it and
  // draw our own robust one via webkitSelectionLayer (see that file).
  '.cm-selectionLayer': { display: 'none' },
  '.cm-wkSelectionBackground': { background: 'rgba(59, 130, 246, 0.25)' },
  '&.cm-focused .cm-wkSelectionBackground': { background: 'rgba(59, 130, 246, 0.35)' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--color-text-muted)',
    border: 'none',
    paddingRight: '4px',
  },
  '.cm-lineNumbers .cm-gutterElement': {
    padding: '0 8px 0 12px',
    minWidth: '2.5em',
    textAlign: 'right',
  },
  '.cm-activeLine': { backgroundColor: 'var(--color-overlay-subtle)' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--color-overlay-hover)', color: 'var(--color-text-tertiary)' },
  // Vim block cursor
  '.cm-fat-cursor': { backgroundColor: 'rgba(59, 130, 246, 0.6) !important' },
  '&:not(.cm-focused) .cm-fat-cursor': { display: 'none' },
  // Search match styling (theme-neutral yellow)
  '.cm-searchMatch': { backgroundColor: 'rgba(255, 200, 0, 0.25)', outline: '1px solid rgba(255, 200, 0, 0.5)' },
  '.cm-searchMatch-selected': { backgroundColor: 'rgba(255, 200, 0, 0.5)' },
  // Search panel
  '.cm-panels': { backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' },
  '.cm-panels.cm-panels-bottom': { borderTop: '1px solid var(--color-border-subtle)' },
  '.cm-search [name="search"], .cm-search [name="replace"]': {
    backgroundColor: 'var(--color-overlay-subtle)',
    color: 'var(--color-text-secondary)',
    border: '1px solid var(--color-border-subtle)',
    borderRadius: '3px',
    padding: '2px 6px',
  },
  '.cm-search button': {
    backgroundColor: 'var(--color-overlay-subtle)',
    color: 'var(--color-text-secondary)',
    border: '1px solid var(--color-border-subtle)',
    borderRadius: '3px',
  },
  // Error decorations
  '.cm-error-line': {
    backgroundColor: 'rgba(239, 68, 68, 0.10)',
    boxShadow: 'inset 2px 0 0 rgba(239, 68, 68, 0.85)',
  },
  '.cm-error-gutter': {
    width: '14px',
    paddingRight: '2px',
  },
  '.cm-error-gutter .cm-gutterElement': {
    color: 'transparent',
  },
  '.cm-error-gutter-marker': {
    color: '#ef4444',
    fontSize: '10px',
    lineHeight: '1',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    cursor: 'pointer',
  },
})

function createView() {
  if (!mountEl.value || view) return
  serverBaseline = props.baselineCode ?? props.code
  view = new EditorView({
    state: EditorState.create({
      doc: props.code,
      extensions: [
        // Vim must come first so its keymap wins over defaults
        vimCompartment.of(getVimExtension()),
        fontCompartment.of(getFontExtension()),
        readOnlyCompartment.of(getReadOnlyExtension()),
        lineNumbers(),
        errorLinesField,
        errorGutter,
        highlightActiveLine(),
        highlightActiveLineGutter(),
        history(),
        drawSelection({ cursorBlinkRate: 1000 }),
        webkitSelectionLayer(),
        search({ top: false }),
        keymap.of([...searchKeymap, ...defaultKeymap, ...historyKeymap]),
        python(),
        highlightCompartment.of(getHighlightExtension()),
        codeTheme,
        EditorView.lineWrapping,
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return
          const next = update.state.doc.toString()
          emit('update:code', next)
          setDirty(next !== serverBaseline)
        }),
      ],
    }),
    parent: mountEl.value,
  })
  bindView(view)
  unregisterVimSaveHandler = registerVimSaveHandler(view, () => emit('save-request'))
  mountEl.value.addEventListener('keydown', vimPanelKeydownHandler, true)
  setDirty(view.state.doc.toString() !== serverBaseline)
  applyErrorLines()
}

function destroyView() {
  mountEl.value?.removeEventListener('keydown', vimPanelKeydownHandler, true)
  unregisterVimSaveHandler?.()
  unregisterVimSaveHandler = null
  view?.destroy()
  view = null
}

function updateCode(code: string) {
  if (!view) return
  if (view.state.doc.toString() === code) return
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: code },
  })
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(getCurrentCode())
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copied.value = false }, 1500)
  } catch (e) {
    console.error('Failed to copy code', e)
  }
}

watch(() => props.code, async (newCode) => {
  await nextTick()
  if (newCode) {
    if (view) {
      updateCode(newCode)
    } else {
      createView()
    }
  } else if (view) {
    updateCode('')
  } else {
    createView()
  }
})

watch(() => props.loading, async () => {
  if (!props.loading) {
    await nextTick()
    if (!view) createView()
  }
})

watch(() => [...(props.errorLines || [])].join(','), () => {
  applyErrorLines()
})

watch(resolvedTheme, () => {
  view?.dispatch({ effects: highlightCompartment.reconfigure(getHighlightExtension()) })
})

watch(() => props.baselineCode, (baseline) => {
  if (!view) return
  serverBaseline = baseline ?? ''
  setDirty(view.state.doc.toString() !== serverBaseline)
})

onMounted(async () => {
  if (!props.loading) {
    await nextTick()
    createView()
  }
})

onUnmounted(() => {
  destroyView()
  if (copiedTimer) clearTimeout(copiedTimer)
})

defineExpose({
  vimEnabled,
  toggleVim,
  monospaceEnabled,
  toggleMonospace,
  copied,
  copyCode,
  dirty,
  getCurrentCode,
  revertToOriginal,
  scrollToLine,
})
</script>

<style>
/* CM6 vim status bar — show pending operator / command line */
.cm-vim-panel {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--color-text-muted);
  background: var(--color-surface);
  border-top: 1px solid var(--color-border, rgba(255, 255, 255, 0.06));
  padding: 2px 12px;
  line-height: 1.5;
}
.cm-vim-panel input {
  font-family: inherit;
  font-size: inherit;
  color: var(--color-text-secondary);
  background: transparent;
  border: none;
  outline: none;
}
</style>
