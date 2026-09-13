<template><div ref="host" class="h-full min-h-0 overflow-auto text-xs" /></template>
<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { syntaxHighlighting } from '@codemirror/language'
import { useTheme } from '../../composables/useTheme'
import { darkHighlightStyle, lightHighlightStyle } from '../../utils/codeHighlight'
import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { json } from '@codemirror/lang-json'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { markdown } from '@codemirror/lang-markdown'
import { sql } from '@codemirror/lang-sql'
const props = defineProps<{ text: string; name: string }>()
const { resolvedTheme } = useTheme()
const host = ref<HTMLElement | null>(null)
let editor: EditorView | null = null
watch([host, () => props.text, () => props.name, resolvedTheme], () => {
  editor?.destroy()
  if (!host.value) return
  const ext = props.name.split('.').pop()?.toLowerCase()
  const language = ext === 'py' ? python() : ['js', 'jsx', 'ts', 'tsx'].includes(ext || '') ? javascript({ typescript: ext === 'ts' || ext === 'tsx', jsx: true }) : ext === 'json' ? json() : ext === 'html' ? html() : ext === 'css' ? css() : ext === 'md' ? markdown() : ext === 'sql' ? sql() : []
  editor = new EditorView({ parent: host.value, state: EditorState.create({ doc: props.text, extensions: [
    EditorState.readOnly.of(true), EditorView.editable.of(false), lineNumbers(), language,
    syntaxHighlighting(resolvedTheme.value === 'light' ? lightHighlightStyle : darkHighlightStyle),
    EditorView.theme({ '&': { height: '100%', color: 'var(--color-text-primary)', fontSize: '12.5px' }, '.cm-content': { padding: '12px 0' }, '.cm-line': { padding: '0 12px' }, '.cm-scroller': { overflow: 'auto', fontFamily: 'monospace' }, '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--color-text-muted)', border: 'none' } }),
  ] }) })
}, { flush: 'post' })
onBeforeUnmount(() => editor?.destroy())
</script>
