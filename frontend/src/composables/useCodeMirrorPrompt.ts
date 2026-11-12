import { ref, onMounted, onUnmounted, type Ref } from 'vue'
import {
  EditorView,
  ViewPlugin,
  ViewUpdate,
  Decoration,
  DecorationSet,
  type PluginValue,
  keymap,
  drawSelection,
  placeholder as cmPlaceholder,
} from '@codemirror/view'
import { EditorState, StateEffect, StateField, Compartment, RangeSetBuilder } from '@codemirror/state'
import { history, defaultKeymap, historyKeymap } from '@codemirror/commands'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { bracketMatching } from '@codemirror/language'
import { registerVimSaveHandler, useVimToggle, vimPanelKeydownHandler } from './codeMirrorVim'
import { webkitSelectionLayer } from './webkitSelectionLayer'
import { lineSyntaxRanges, type PromptSyntaxKind, type PromptSyntaxMode } from '../utils/promptSyntax'

// --- Diff decoration effects ---
const addDiffEffect = StateEffect.define<{ from: number; to: number }[]>()
const clearDiffEffect = StateEffect.define<null>()

const diffField = StateField.define<DecorationSet>({
  create() {
    return Decoration.none
  },
  update(decos, tr) {
    // Map through document changes so positions stay valid
    decos = decos.map(tr.changes)
    for (const effect of tr.effects) {
      if (effect.is(addDiffEffect)) {
        const builder = new RangeSetBuilder<Decoration>()
        const sorted = [...effect.value].sort((a, b) => a.from - b.from)
        for (const { from, to } of sorted) {
          if (from < to) {
            builder.add(from, to, diffMark)
          }
        }
        decos = builder.finish()
      }
      if (effect.is(clearDiffEffect)) {
        decos = Decoration.none
      }
    }
    return decos
  },
  provide: (f) => EditorView.decorations.from(f),
})

const diffMark = Decoration.mark({ class: 'cm-diff-added' })

// --- How the prompt will be read: drives what the highlighter marks ---
// (see PromptSyntaxMode in utils/promptSyntax.ts, which also holds the tokenizer)
export type { PromptSyntaxMode }
interface SyntaxConfig { mode: PromptSyntaxMode; known: Set<string> }
const setSyntaxEffect = StateEffect.define<SyntaxConfig>()
const syntaxField = StateField.define<SyntaxConfig>({
  create: () => ({ mode: 'enhance', known: new Set() }),
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setSyntaxEffect)) value = e.value
    return value
  },
})

// --- Prompt syntax highlighting plugin ---
function promptSyntaxHighlighter() {
  return ViewPlugin.fromClass(
    class implements PluginValue {
      decorations: DecorationSet

      syntax: SyntaxConfig = { mode: 'enhance', known: new Set() }

      constructor(view: EditorView) {
        this.decorations = this.buildDecorations(view)
      }

      update(update: ViewUpdate) {
        const reconfigured = update.transactions.some(tr => tr.effects.some(e => e.is(setSyntaxEffect)))
        if (update.docChanged || update.viewportChanged || reconfigured) {
          this.decorations = this.buildDecorations(update.view)
        }
      }

      buildDecorations(view: EditorView): DecorationSet {
        const builder = new RangeSetBuilder<Decoration>()
        const { from, to } = view.viewport
        this.syntax = view.state.field(syntaxField)
        const { mode } = this.syntax
        if (mode === 'raw') return builder.finish()

        for (let pos = from; pos < to; ) {
          const line = view.state.doc.lineAt(pos)
          for (const r of lineSyntaxRanges(line.text, this.syntax)) {
            builder.add(line.from + r.from, line.from + r.to, SYNTAX_DECO[r.kind])
          }
          pos = line.to + 1
        }
        return builder.finish()
      }
    },
    { decorations: (v) => v.decorations }
  )
}

const wildcardDeco = Decoration.mark({ class: 'cm-wildcard' })
const namedWildcardDeco = Decoration.mark({ class: 'cm-named-wildcard' })
const commentDeco = Decoration.mark({ class: 'cm-comment-line' })
// Plain mode (no chat model reads this prompt): # lines are for a model.
const unreadCommentDeco = Decoration.mark({ class: 'cm-comment-line', attributes: { title: 'No chat model reads this prompt, so # lines are left out of it.' } })
// A {{name}} that isn't a saved wildcard or segment: nothing fills it.
const unknownNameDeco = Decoration.mark({ class: 'cm-needs-enhance', attributes: { title: 'Not a saved wildcard or segment, so nothing fills it.' } })
const slotDeco = Decoration.mark({ class: 'cm-slot' })
const verbatimDeco = Decoration.mark({ class: 'cm-verbatim' })
const SYNTAX_DECO: Record<PromptSyntaxKind, Decoration> = {
  'wildcard': wildcardDeco,
  'named-wildcard': namedWildcardDeco,
  'unknown-name': unknownNameDeco,
  'slot': slotDeco,
  'comment': commentDeco,
  'comment-unread': unreadCommentDeco,
  'verbatim': verbatimDeco,
}

// --- Theme ---
const stimmaTheme = EditorView.theme({
  '&': {
    fontSize: '14px',
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    backgroundColor: 'var(--color-surface)',
    // The embedder sizes the box (AIPromptEditor sets these from its rows on
    // phones). A variable, not a value read here: this theme is built once per
    // page, before the viewport is final, and must follow a fold or a resize.
    minHeight: 'var(--prompt-min-h, 200px)',
    maxHeight: 'var(--prompt-max-h, 408px)', // ~20 rows * 20px + 8px padding
    borderRadius: '0.375rem 0.375rem 0 0', // match parent's rounded-md, flat bottom
  },
  '&.cm-focused': {
    outline: 'none',
  },
  // Vim command-line / status bar lives in a bottom panel. Override CM6's
  // base-theme defaults (which paint a near-white top border) with our tokens.
  '.cm-panels': {
    backgroundColor: 'var(--color-surface)',
    color: 'var(--color-text-secondary)',
  },
  '.cm-panels.cm-panels-bottom': {
    borderTop: '1px solid var(--color-border-subtle)',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'inherit',
    lineHeight: '1.5',
    scrollbarWidth: 'thin',
    scrollbarColor: 'rgba(156, 163, 175, 0.3) transparent',
    flexGrow: '1',
  },
  '.cm-scroller::-webkit-scrollbar': {
    width: '6px',
  },
  '.cm-scroller::-webkit-scrollbar-track': {
    background: 'transparent',
  },
  '.cm-scroller::-webkit-scrollbar-thumb': {
    background: 'rgba(156, 163, 175, 0.3)',
    borderRadius: '3px',
  },
  '.cm-scroller::-webkit-scrollbar-thumb:hover': {
    background: 'rgba(156, 163, 175, 0.5)',
  },
  '.cm-content': {
    caretColor: 'var(--color-text-secondary)',
    color: 'var(--color-text-secondary)',
    // CodeMirror expects vertical padding here (not on .cm-scroller) so the
    // selection layer's coordinate origin matches measured text. Putting it on
    // .cm-scroller drifts the drawn selection on WebKit (codemirror/dev#1149).
    padding: '8px 0 0 0',
    borderBottom: 'none',
    outline: 'none',
  },
  '.cm-line': {
    // Horizontal padding belongs on .cm-line per CodeMirror's styling docs.
    padding: '0 12px',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--color-text-secondary)',
  },
  // Selection color for both modes. By default we use the browser's NATIVE
  // selection (drawSelection is only enabled in vim mode — see
  // getSelectionExtension) because CodeMirror's drawn selection drifts and
  // mis-heights on WebKit/WKWebView (codemirror/dev#1149, won't-fix).
  '& ::selection': {
    backgroundColor: 'rgba(59, 130, 246, 0.25)',
  },
  // In vim mode we hide CM's own (buggy on WebKit) drawn selection background
  // and draw our own via webkitSelectionLayer. The cursor layer is untouched.
  '.cm-selectionLayer': {
    display: 'none',
  },
  '.cm-wkSelectionBackground': {
    background: 'rgba(59, 130, 246, 0.25)',
  },
  '.cm-activeLine': {
    backgroundColor: 'transparent',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'transparent',
  },
  '.cm-gutters': {
    display: 'none',
  },
  '.cm-placeholder': {
    color: 'var(--color-text-muted)',
    fontStyle: 'normal',
  },
  // Bracket matching
  '.cm-matchingBracket': {
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    outline: '1px solid rgba(59, 130, 246, 0.4)',
  },
  '.cm-nonmatchingBracket': {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
  },
  // Prompt syntax colors
  '.cm-wildcard': {
    color: '#16a34a', // green-600
    backgroundColor: 'rgba(34, 197, 94, 0.1)',
    borderRadius: '2px',
    padding: '0 1px',
  },
  '.cm-named-wildcard': {
    color: '#d97706', // amber-600
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    borderRadius: '2px',
    padding: '0 1px',
  },
  '.cm-slot': {
    color: '#7c3aed', // violet-600
    backgroundColor: 'rgba(139, 92, 246, 0.1)',
    borderRadius: '2px',
    padding: '0 1px',
  },
  '.cm-needs-enhance': {
    color: '#ef4444', // red-500: an error in the prompt, the run waits on it
    textDecoration: 'underline wavy rgba(239, 68, 68, 0.8)',
    textUnderlineOffset: '3px',
  },
  '.cm-comment-line': {
    color: '#6b7280', // gray-500 — more muted than body text
    fontStyle: 'italic',
  },
  '.cm-verbatim': {
    color: '#3b82f6', // blue-500
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderRadius: '2px',
    padding: '0 1px',
  },
  // Diff animation
  '.cm-diff-added': {
    color: '#c084fc',
    textShadow: '0 0 8px rgba(192, 132, 252, 0.5)',
    animation: 'cm-fadeToNormal 3s ease-out forwards',
  },
  // Vim cursor styling
  '.cm-fat-cursor': {
    backgroundColor: 'rgba(59, 130, 246, 0.8) !important',
  },
  '&:not(.cm-focused) .cm-fat-cursor': {
    display: 'none',
  },
  '&:not(.cm-focused) .cm-cursor': {
    display: 'none !important',
  },
})

// Global keyframe injection (only once)
let keyframesInjected = false
function injectKeyframes() {
  if (keyframesInjected) return
  keyframesInjected = true
  const style = document.createElement('style')
  style.textContent = `
    @keyframes cm-fadeToNormal {
      0% {
        color: #c084fc;
        text-shadow: 0 0 8px rgba(192, 132, 252, 0.5);
      }
      100% {
        color: var(--color-text-secondary);
        text-shadow: none;
      }
    }
  `
  document.head.appendChild(style)
}

// --- Composable ---
interface UseCodeMirrorPromptOptions {
  mountRef: Ref<HTMLElement | null>
  modelValue: () => string
  placeholder?: string
  onChange: (value: string) => void
  onBlur: () => void
  /** Vim :w / :wq / :x. */
  onSave?: () => void
}

export function useCodeMirrorPrompt(options: UseCodeMirrorPromptOptions) {
  const { mountRef, modelValue, placeholder, onChange, onBlur, onSave } = options

  let view: EditorView | null = null
  let ignoreNextChange = false
  let unregisterSave: (() => void) | null = null

  const { vimEnabled, vimCompartment, getVimExtension, toggleVim: baseToggleVim, bindView } = useVimToggle()
  const fontCompartment = new Compartment()

  // drawSelection is enabled only alongside vim — vim's block cursor and visual
  // mode are built around CodeMirror's drawn selection (vim manages its selection
  // virtually, so there's no native DOM selection to paint). Outside vim we leave
  // it off and let the browser paint the native selection (see stimmaTheme).
  //
  // We keep drawSelection for its cursor layer + native-selection hiding, but its
  // own selection background drifts/gaps on WebKit (see webkitSelectionLayer), so
  // we hide that one (.cm-selectionLayer in stimmaTheme) and draw our own robust
  // background via webkitSelectionLayer().
  const selectionCompartment = new Compartment()
  function getSelectionExtension() {
    return vimEnabled.value ? [drawSelection({ cursorBlinkRate: 1000 }), webkitSelectionLayer()] : []
  }
  function toggleVim() {
    baseToggleVim()
    view?.dispatch({ effects: selectionCompartment.reconfigure(getSelectionExtension()) })
  }
  const monospaceEnabled = ref(localStorage.getItem('stimma:monospace-font') === 'true')

  const monoFontTheme = EditorView.theme({
    '&': {
      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: '13px',
    },
    '.cm-scroller': {
      fontFamily: 'inherit',
    },
  })

  function getFontExtension() {
    return monospaceEnabled.value ? monoFontTheme : []
  }

  function createEditor() {
    if (!mountRef.value) return

    injectKeyframes()

    const startState = EditorState.create({
      doc: modelValue(),
      extensions: [
        vimCompartment.of(getVimExtension()),
        fontCompartment.of(getFontExtension()),
        selectionCompartment.of(getSelectionExtension()),
        history(),
        bracketMatching(),
        closeBrackets(),
        // Allow auto-close brackets regardless of the character after the cursor
        EditorState.languageData.of(() => [{
          closeBrackets: { before: ')]}:;>\'"`~!@#$%^&*(-_=+\\|,.<>/?0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ' },
        }]),
        EditorView.domEventHandlers({
          keydown(event) {
            // Let Cmd/Ctrl+Enter bubble up to the app
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              return false // don't handle, let it propagate
            }
          },
        }),
        keymap.of([
          // Block CM6 from inserting a newline on Mod+Enter
          { key: 'Mod-Enter', run: () => true },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        cmPlaceholder(placeholder || 'Describe the image you want to generate...'),
        stimmaTheme,
        syntaxField,
        promptSyntaxHighlighter(),
        diffField,
        EditorView.updateListener.of((update: ViewUpdate) => {
          if (update.docChanged && !ignoreNextChange) {
            onChange(update.state.doc.toString())
          }
          ignoreNextChange = false

          if (update.focusChanged && !update.view.hasFocus) {
            onBlur()
          }
        }),
        EditorView.lineWrapping,
      ],
    })

    view = new EditorView({
      state: startState,
      parent: mountRef.value,
    })
    if (pendingSyntax) { view.dispatch({ effects: setSyntaxEffect.of(pendingSyntax) }); pendingSyntax = null }

    // Wire up vim persistence: replay mappings + capture ex commands typed in the : panel
    bindView(view)
    if (onSave) unregisterSave = registerVimSaveHandler(view, onSave)
    mountRef.value.addEventListener('keydown', vimPanelKeydownHandler, true)
  }

  function setContent(text: string) {
    if (!view) return
    const current = view.state.doc.toString()
    if (current === text) return
    ignoreNextChange = true
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: text },
    })
  }

  function toggleMonospace() {
    monospaceEnabled.value = !monospaceEnabled.value
    localStorage.setItem('stimma:monospace-font', String(monospaceEnabled.value))
    if (view) {
      view.dispatch({
        effects: fontCompartment.reconfigure(getFontExtension()),
      })
    }
  }

  function applyDiffDecorations(segments: { text: string; type: 'added' | 'removed' | 'unchanged' }[]) {
    if (!view) return

    const ranges: { from: number; to: number }[] = []
    let pos = 0
    for (const seg of segments) {
      if (seg.type === 'removed') continue
      if (seg.type === 'added') {
        ranges.push({ from: pos, to: pos + seg.text.length })
      }
      pos += seg.text.length
    }

    if (ranges.length === 0) return

    view.dispatch({
      effects: addDiffEffect.of(ranges),
    })
  }

  function clearDiffDecorations() {
    if (!view) return
    view.dispatch({
      effects: clearDiffEffect.of(null),
    })
  }

  function focus() {
    view?.focus()
  }

  let pendingSyntax: SyntaxConfig | null = null
  /** How the prompt will be read (see PromptSyntaxMode), with the global wildcard and segment names. */
  function setSyntax(mode: PromptSyntaxMode, knownNames: Iterable<string>) {
    const next = { mode, known: new Set([...knownNames].map(n => n.trim().toLowerCase())) }
    if (!view) { pendingSyntax = next; return }
    view.dispatch({ effects: setSyntaxEffect.of(next) })
  }

  /** Select one line (1-based) and bring it into view: "show me where this came from". */
  function selectLine(n: number) {
    if (!view) return
    const doc = view.state.doc
    if (n < 1 || n > doc.lines) return
    const line = doc.line(n)
    view.dispatch({ selection: { anchor: line.from, head: line.to }, scrollIntoView: true })
    view.focus()
  }

  function destroy() {
    mountRef.value?.removeEventListener('keydown', vimPanelKeydownHandler, true)
    unregisterSave?.()
    unregisterSave = null
    view?.destroy()
    view = null
  }

  onMounted(() => {
    createEditor()
  })

  onUnmounted(() => {
    destroy()
  })

  return {
    vimEnabled,
    monospaceEnabled,
    toggleVim,
    toggleMonospace,
    setContent,
    applyDiffDecorations,
    clearDiffDecorations,
    focus,
    selectLine,
    setSyntax,
    destroy,
  }
}
