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

// Plain markup gets readable defaults; the agent's CSS overrides any of them.
const BASE = [
  'text-[14px] leading-[1.55] text-content',
  '[&_h1]:mb-2.5 [&_h1]:font-brand [&_h1]:text-[28px] [&_h1]:font-semibold [&_h1]:leading-tight [&_h1]:tracking-[-0.015em]',
  '[&_h2]:mb-2 [&_h2]:font-brand [&_h2]:text-[18px] [&_h2]:font-semibold',
  '[&_h3]:mb-1 [&_h3]:font-brand [&_h3]:text-[15px] [&_h3]:font-semibold',
  '[&_p]:mb-2.5 [&_p]:text-content-secondary [&_b]:font-semibold [&_b]:text-content [&_strong]:font-semibold [&_strong]:text-content',
  '[&_a]:text-accent [&_a]:underline [&_ul]:mb-2.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2.5 [&_ol]:list-decimal [&_ol]:pl-5',
  '[&_hr]:my-6 [&_hr]:border-edge-subtle',
].join(' ')

export default defineComponent({
  props: { scope: { type: String, required: true }, css: { type: String, default: '' } },
  setup(props) {
    const sheet = useSheetContext()
    return () => h('div', { 'data-sheet-scope': props.scope, class: BASE, style: THEME }, [
      props.css ? h('style', props.css) : null,
      ...(sheet.root.value ? sheetToVNodes(Array.from(sheet.root.value.childNodes), COMPONENTS) : []),
    ])
  },
})
</script>
