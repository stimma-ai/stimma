import { createApp, h, ref } from 'vue'
import { EditorView, keymap } from '@codemirror/view'
import { indentWithTab } from '@codemirror/commands'
import Modal from '../../src/components/ui/Modal.vue'
import Tooltip from '../../src/components/ui/Tooltip.vue'
import { useGlobalKeyboardShortcuts } from '../../src/composables/useGlobalKeyboardShortcuts'
import '../../src/style.css'

const show = ref(false), nested = ref(false), empty = ref(false)
const label = ref('Remove item')
const shortcuts: string[] = []
let editor: EditorView
Object.assign(window, { modalFocus: {
  shortcuts,
  empty: () => { empty.value = true },
  rename: () => { label.value = 'Delete item' },
  editorText: () => editor.state.doc.toString(),
} })
createApp({
  setup() {
    useGlobalKeyboardShortcuts({ onKeydown: (event: KeyboardEvent) => {
      if (event.key === 'Delete' || ((event.metaKey || event.ctrlKey) && event.key === 'a')) shortcuts.push(event.key)
    } })
    return () => h('div', [
      h('button', { onClick: () => { show.value = true } }, 'Open dialog'),
      h('button', {}, 'Outside'),
      h(Tooltip, { text: label.value }, () => h('button', { 'data-icon': '' }, [h('svg', { 'aria-hidden': 'true' })])),
      h(Tooltip, { text: 'Tooltip text' }, () => h('button', { 'aria-label': 'Explicit name' })),
      h(Tooltip, { text: 'Other tooltip' }, () => h('button', {}, 'Visible name')),
      h(Modal, { show: show.value, onClose: () => { show.value = false } }, () => [
        h('button', {}, 'First'),
        h('input', { 'aria-label': 'Dialog field' }),
        h('button', { disabled: true }, 'Disabled'),
        h('button', { style: 'display:none' }, 'Hidden'),
        h('div', { inert: true }, h('button', {}, 'Inert')),
        h('button', { onClick: () => { nested.value = true } }, 'Open nested'),
        h('div', { key: 'editor', ref: (el: HTMLElement | null) => {
          if (el && !editor) editor = new EditorView({ parent: el, doc: 'text', extensions: [keymap.of([indentWithTab])] })
        } }),
        h('button', {}, 'Last'),
      ]),
      h(Modal, { show: nested.value, nested: true, onClose: () => { nested.value = false } }, () => [
        h('button', {}, 'Nested first'), h('button', {}, 'Nested last'),
      ]),
      h(Modal, { show: empty.value, nested: true, onClose: () => { empty.value = false } }),
    ])
  },
}).mount('#app')
