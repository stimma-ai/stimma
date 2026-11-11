import { createApp, defineComponent, h, onMounted, ref, type FunctionalComponent } from 'vue'
import '../../src/style.css'
import ProvenanceSteps from '../../src/provenance/ProvenanceSteps.vue'
import { provideProvenanceHost } from '../../src/provenance/host'
import type { ViewStep } from '../../src/provenance/types'
import { useCodeMirrorPrompt, type PromptSyntaxMode } from '../../src/composables/useCodeMirrorPrompt'

// The media info panel's "how it was made" steps, mounted with a stand-in host:
// copies land in window.copied, thumbnails are blank tiles.
const copied: string[] = ((window as any).copied = [])

const made = 'A candid photo of a woman with curtain bangs in a yellow raincoat, standing on a rainy Lisbon street at dusk, soft neon reflections on wet cobblestones, ohwx woman, 35mm film grain, shallow depth of field'
const typed = [
  'A candid photo of a woman with {{hairstyle}} in a {yellow|red|navy} raincoat,',
  'standing on a {rainy|foggy} {Lisbon|Porto} street at dusk, [ohwx woman], 35mm film grain',
  '# keep her face the same between images, vary the street',
].join('\n')

function step(over: Partial<ViewStep>): ViewStep {
  return {
    key: 'self', tool: 'Flux.2 Klein 9B', icon: 'text-to-image', date: new Date(Date.now() - 3 * 3600e3).toISOString(),
    imported: false, prompt: null, negativePrompt: null, originalPrompt: null,
    facts: [
      { key: 'seed', label: 'Seed', value: '1844120931', mono: true, truncate: false },
      { key: 'steps', label: 'Steps', value: '4', mono: true, truncate: false },
      { key: 'size', label: 'Size', value: '1216 × 832', mono: true, truncate: false },
    ],
    inputs: [], editSteps: [], rawMetadata: null,
    ...over,
  }
}

const CASES: Record<string, ViewStep[]> = {
  single: [step({ prompt: made })],
  pair: [step({ prompt: made, originalPrompt: typed })],
  identical: [step({ prompt: made, originalPrompt: `${made}  ` })],
}

const Thumb: FunctionalComponent = () => h('div', { class: 'w-full h-full bg-overlay-subtle' })

const Host = defineComponent({
  props: { steps: { type: Array, required: true } },
  setup(props) {
    provideProvenanceHost({ thumbnail: Thumb, copy: (text: string) => { copied.push(text) } })
    return () => h('div', { class: 'p-4', 'data-panel': '' }, [
      h('h4', { class: 'm-0 mb-2 text-xs font-semibold text-content-secondary' }, 'Lineage'),
      h(ProvenanceSteps, { steps: props.steps as ViewStep[] }),
    ])
  },
})

let app: ReturnType<typeof createApp> | null = null
;(window as any).mountCase = (name: string, width: number) => {
  app?.unmount()
  const el = document.getElementById('app')!
  el.style.width = `${width}px`
  app = createApp(Host, { steps: CASES[name] })
  app.mount(el)
}
;(window as any).TYPED = typed
;(window as any).MADE = made

// The prompt editor itself, to hold its highlighting to the read-only view's.
const Editor = defineComponent({
  props: { text: { type: String, required: true }, mode: { type: String, required: true }, known: { type: Array, default: () => [] } },
  setup(props) {
    const mountRef = ref<HTMLElement | null>(null)
    const { setSyntax } = useCodeMirrorPrompt({ mountRef, modelValue: () => props.text, onChange: () => {}, onBlur: () => {} })
    onMounted(() => setSyntax(props.mode as PromptSyntaxMode, props.known as string[]))
    return () => h('div', { ref: mountRef, 'data-editor': '' })
  },
})
;(window as any).mountEditor = (text: string, mode: string, known: string[] = []) => {
  app?.unmount()
  const el = document.getElementById('app')!
  el.style.width = '600px'
  app = createApp(Editor, { text, mode, known })
  app.mount(el)
}
