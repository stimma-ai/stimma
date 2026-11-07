<script lang="ts">
// Renders the parsed sheet: the agent's markup as itself, kit elements as live
// components, and the agent's CSS scoped to this sheet. The --cs-* variables
// are the sheet theme (the package cover kit's names, bound to app tokens), so
// agent CSS written against them reads as Stimma in both themes.
import { defineComponent, h } from 'vue'
import { sheetToVNodes } from './sheetHtml'
import { useSheetContext } from './useContactSheet'
import SheetSection from './SheetSection.vue'
import SheetMediaGroup from './SheetMediaGroup.vue'
import SheetMedia from './SheetMedia.vue'
import SheetColumns from './SheetColumns.vue'
import SheetColumn from './SheetColumn.vue'
import SheetCompare from './SheetCompare.vue'
import SheetCheck from './SheetCheck.vue'
import SheetChoice from './SheetChoice.vue'
import SheetRating from './SheetRating.vue'
import SheetField from './SheetField.vue'

const COMPONENTS = {
  'stimma-section': SheetSection,
  'stimma-media-group': SheetMediaGroup,
  'stimma-media': SheetMedia,
  'stimma-columns': SheetColumns,
  'stimma-column': SheetColumn,
  'stimma-compare': SheetCompare,
  'stimma-check': SheetCheck,
  'stimma-choice': SheetChoice,
  'stimma-rating': SheetRating,
  'stimma-field': SheetField,
}

const THEME = {
  '--cs-bg': 'var(--color-base)',
  '--cs-fg': 'var(--color-text-primary)',
  '--cs-muted': 'var(--color-text-secondary)',
  '--cs-faint': 'var(--color-text-muted)',
  '--cs-line': 'var(--color-border-subtle)',
  '--cs-accent': 'var(--color-accent)',
  '--cs-plate': 'var(--color-overlay-subtle)',
  '--cs-display': "'General Sans', ui-sans-serif, system-ui, sans-serif",
  '--cs-mono': "ui-monospace, 'SF Mono', Menlo, monospace",
}

// Plain markup gets readable defaults. They sit in the sheet's scope at zero
// specificity (:where), so any rule the agent writes wins over them.
const baseCss = (scope: string) => `@scope (${scope}) {
:where(h1) { margin: 0 0 10px; font-family: var(--cs-display); font-size: 28px; font-weight: 600; line-height: 1.15; letter-spacing: -0.015em; color: var(--cs-fg); }
:where(h2) { margin: 0 0 8px; font-family: var(--cs-display); font-size: 18px; font-weight: 600; color: var(--cs-fg); }
:where(h3) { margin: 0 0 4px; font-family: var(--cs-display); font-size: 15px; font-weight: 600; color: var(--cs-fg); }
:where(p) { margin: 0 0 10px; color: var(--cs-muted); }
:where(b, strong) { font-weight: 600; color: var(--cs-fg); }
:where(a) { color: var(--cs-accent); text-decoration: underline; }
:where(ul) { margin: 0 0 10px; padding-left: 20px; list-style: disc; }
:where(ol) { margin: 0 0 10px; padding-left: 20px; list-style: decimal; }
:where(hr) { margin: 24px 0; border: 0; border-top: 1px solid var(--cs-line); }
}`

export default defineComponent({
  props: { scope: { type: String, required: true }, css: { type: String, default: '' } },
  setup(props) {
    const sheet = useSheetContext()
    const scopeSelector = `[data-sheet-scope="${props.scope}"]`
    return () => h('div', { 'data-sheet-scope': props.scope, class: 'text-[14px] leading-[1.55] text-content', style: THEME }, [
      h('style', baseCss(scopeSelector)),
      props.css ? h('style', props.css) : null,
      ...(sheet.root.value ? sheetToVNodes(Array.from(sheet.root.value.childNodes), COMPONENTS) : []),
    ])
  },
})
</script>
