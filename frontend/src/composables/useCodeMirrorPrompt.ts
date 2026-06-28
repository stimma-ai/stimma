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
import { useVimToggle, vimPanelKeydownHandler } from './codeMirrorVim'
import { webkitSelectionLayer } from './webkitSelectionLayer'

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

// --- Prompt syntax highlighting plugin ---
function promptSyntaxHighlighter() {
  return ViewPlugin.fromClass(
    class implements PluginValue {
      decorations: DecorationSet

      constructor(view: EditorView) {
        this.decorations = this.buildDecorations(view)
      }

      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = this.buildDecorations(update.view)
        }
      }

      buildDecorations(view: EditorView): DecorationSet {
        const builder = new RangeSetBuilder<Decoration>()
        const { from, to } = view.viewport

        for (let pos = from; pos < to; ) {
          const line = view.state.doc.lineAt(pos)
          const text = line.text

          // Comment lines: # at start of line
          if (/^\s*#/.test(text)) {
            builder.add(line.from, line.to, commentDeco)
          } else {
            // Collect all ranges for this line, then sort before adding
            const ranges: { from: number; to: number; deco: Decoration }[] = []
            const namedRanges = this.findNamedWildcards(text, line.from, ranges)
            this.findBraceGroups(text, line.from, ranges, namedRanges)
            this.findVerbatim(text, line.from, ranges)
            ranges.sort((a, b) => a.from - b.from)
            for (const r of ranges) {
              builder.add(r.from, r.to, r.deco)
            }
          }

          pos = line.to + 1
        }
        return builder.finish()
      }

      findNamedWildcards(text: string, lineStart: number, out: { from: number; to: number; deco: Decoration }[]): { from: number; to: number }[] {
        const skipRanges: { from: number; to: number }[] = []
        const re = /\{\{([^{}]+)\}\}/g
        let match
        while ((match = re.exec(text)) !== null) {
          const from = lineStart + match.index
          const to = from + match[0].length
          out.push({ from, to, deco: namedWildcardDeco })
          skipRanges.push({ from: match.index, to: match.index + match[0].length })
        }
        return skipRanges
      }

      findBraceGroups(text: string, lineStart: number, out: { from: number; to: number; deco: Decoration }[], skipRanges: { from: number; to: number }[] = []) {
        // Match nested braces containing at least one pipe
        let i = 0
        while (i < text.length) {
          // Skip positions inside named wildcard ranges
          if (skipRanges.some(r => i >= r.from && i < r.to)) {
            i++
            continue
          }
          if (text[i] === '{') {
            const start = i
            let depth = 1
            i++
            let hasPipe = false
            while (i < text.length && depth > 0) {
              if (text[i] === '{') depth++
              else if (text[i] === '}') depth--
              else if (text[i] === '|' && depth === 1) hasPipe = true
              i++
            }
            if (depth === 0 && hasPipe) {
              out.push({ from: lineStart + start, to: lineStart + i, deco: wildcardDeco })
            }
          } else {
            i++
          }
        }
      }

      findVerbatim(text: string, lineStart: number, out: { from: number; to: number; deco: Decoration }[]) {
        const re = /\[([^\]]+)\]/g
        let match
        while ((match = re.exec(text)) !== null) {
          out.push({ from: lineStart + match.index, to: lineStart + match.index + match[0].length, deco: verbatimDeco })
        }
      }
    },
    { decorations: (v) => v.decorations }
  )
}

const wildcardDeco = Decoration.mark({ class: 'cm-wildcard' })
const namedWildcardDeco = Decoration.mark({ class: 'cm-named-wildcard' })
const commentDeco = Decoration.mark({ class: 'cm-comment-line' })
const verbatimDeco = Decoration.mark({ class: 'cm-verbatim' })

// --- Theme ---
const stimmaTheme = EditorView.theme({
  '&': {
    fontSize: '14px',
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    backgroundColor: 'var(--color-surface)',
    minHeight: '200px',
    maxHeight: '408px', // ~20 rows * 20px + 8px padding
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
}

export function useCodeMirrorPrompt(options: UseCodeMirrorPromptOptions) {
  const { mountRef, modelValue, placeholder, onChange, onBlur } = options

  let view: EditorView | null = null
  let ignoreNextChange = false

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

    // Wire up vim persistence: replay mappings + capture ex commands typed in the : panel
    bindView(view)
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

  function destroy() {
    mountRef.value?.removeEventListener('keydown', vimPanelKeydownHandler, true)
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
    destroy,
  }
}
