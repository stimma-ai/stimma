import { computed, createApp, h, ref } from 'vue'
import axios from 'axios'
import '../../src/style.css'
import AIPromptEditor from '../../src/components/generation/AIPromptEditor.vue'
import FluentPicker from '../../src/components/generation/FluentPicker.vue'
import PromptSlotLines from '../../src/components/generation/PromptSlotLines.vue'
import PromptSlotHover from '../../src/components/generation/PromptSlotHover.vue'
import KeepFromThisCard from '../../src/components/generation/KeepFromThisCard.vue'
import { usePromptProgram } from '../../src/composables/usePromptProgram'
import type { ChoicePool, ProgramChoice, ProgramSlot, Variant } from '../../src/utils/programWire'

// Tool View's prompt card in Fluent as ToolView wires it: the real editor with Fluent's marks,
// the lines under it, the slot's picker, the hover card and Keep from this, on the real
// composable, against a stand-in server answering /prepare, /pools and /options in the shapes
// of the contract (stimma-plans VARIANTS_IMPL.md section 4). Each slot has a pool of variants;
// a person also has descent (Region > heritage) and gender. A seed picked that no variant
// matches makes the server write for it (`more` while it does). `window.calls` records what was
// sent; `window.hold(id)` keeps a slot's variants "being written".

export const PROMPT = '<dominant young woman> taking a low quality cell phone <type of selfie> in a living room, wearing <clothing slightly open in the front>, lit by <lighting>, {summer|autumn|winter|spring}'

const at = (words: string) => { const i = PROMPT.indexOf(`<${words}>`); return [i, i + words.length + 2] as [number, number] }
const slot = (id: string, n: number, kind: ProgramSlot['kind'], label: string, words: string): ProgramSlot =>
  ({ id, n, kind, label, words, span: at(words), line: 1, state: 'ready' })
const SLOTS = [
  slot('woman', 1, 'person', 'Woman', 'dominant young woman'),
  slot('selfie', 2, 'free', 'Selfie', 'type of selfie'),
  slot('clothing', 3, 'free', 'Clothing', 'clothing slightly open in the front'),
  slot('lighting', 4, 'light', 'Lighting', 'lighting'),
]
const CHOICES: ProgramChoice[] = [
  ...SLOTS.map(s => ({ id: s.id, kind: 'variants' as const, label: s.label, slot: s.id })),
  { id: 'list1', kind: 'pick', label: 'Season', source: 'list', line: 1, options: ['summer', 'autumn', 'winter', 'spring'] },
]

const w = (descent: string, gender: string, rest: string): Variant =>
  ({ text: `dominant young woman of ${descent} descent ${rest}`, seeds: { descent, gender } })
const POOLS: Record<string, Variant[]> = {
  woman: [
    w('Korean', 'woman', 'with a sharp black bob and a cool, level stare'),
    w('Irish', 'woman', 'with copper curls pinned up, one eyebrow raised'),
    w('Swedish', 'trans woman', 'with close-cropped bleached hair and a septum ring'),
    w('Nigerian', 'woman', 'with long box braids and gold hoops'),
    w('Japanese', 'woman', 'with an asymmetric silver bob'),
    w('Brazilian', 'woman', 'with a high ponytail and flushed cheeks'),
  ],
  selfie: ['high-angle selfie, arm stretched above her head', 'mirror selfie in a smudged full-length mirror',
    'low-angle selfie from her lap, chin toward the lens', 'flash selfie at arm’s length, red-eye and hard shadows']
    .map(text => ({ text, seeds: { core: text.split(' ')[0] } })),
  clothing: ['a white cardigan slightly open in the front', 'a satin robe slightly open in the front',
    'an oversized flannel shirt slightly open in the front'].map(text => ({ text })),
  lighting: ['soft window light from the left', 'the cold glow of a TV screen', 'a warm floor lamp behind the couch'].map(text => ({ text })),
}
const MORE = ['a denim jacket slightly open in the front', 'a silk pajama top slightly open in the front', 'a knitted cardigan slightly open in the front']
const DESCENT = [
  { id: 'East Asia', values: ['Korean', 'Japanese', 'Chinese'] },
  { id: 'Northern Europe', values: ['Irish', 'Swedish', 'Danish'] },
  { id: 'Sub-Saharan Africa', values: ['Nigerian', 'Ethiopian'] },
  { id: 'Latin America and the Caribbean', values: ['Brazilian', 'Mexican'] },
]
const GENDERS = ['woman', 'man', 'trans woman', 'trans man', 'non-binary person']

const calls: Array<{ url: string; body: any }> = ((window as any).calls = [])
const held = new Set<string>((window as any).HOLD || [])
;(window as any).hold = (id: string) => { held.add(id) }
;(window as any).release = (id: string) => { held.delete(id) }
// Seeds the server is writing for, by slot: until then, `more`.
const writingFor = new Map<string, number>()
// How long More like these takes here.
const moreMs = ref(500)
;(window as any).slowMore = (ms: number) => { moreMs.value = ms }

function matches(v: Variant, seeds: any): boolean {
  const regions: string[] = seeds?.descent?.groups?.region || []
  const heritages = [...(seeds?.descent?.values || []), ...regions.flatMap(r => DESCENT.find(d => d.id === r)?.values || [])]
  if (heritages.length && !heritages.includes(v.seeds?.descent || '')) return false
  const genders: string[] = seeds?.gender?.values || []
  return !genders.length || genders.includes(v.seeds?.gender || '')
}

function poolFor(id: string, choice: any): ChoicePool {
  const state = held.has(id) ? 'writing' : 'ready'
  const variants = state === 'ready' ? [...POOLS[id], ...(choice?.add || []).map((text: string) => ({ text, own: true }))] : []
  // A picked heritage nothing in the pool has: the writer writes some for it, in the background.
  const picked: string[] = choice?.seeds?.descent?.values || []
  const missing = picked.find(h => !POOLS.woman.some(v => v.seeds?.descent === h))
  if (id === 'woman' && missing && !writingFor.has(id)) {
    writingFor.set(id, 1)
    setTimeout(() => {
      const gender = choice.seeds.gender?.values?.[0] || 'woman'
      POOLS.woman.push(w(missing, gender, 'with a choppy fringe'), w(missing, gender, 'with long waves'))
      writingFor.delete(id)
    }, 700)
  }
  const more = writingFor.has(id)
  return {
    kind: 'variants', state, more, variants, options: variants.map(v => v.text), chosen: choice || null,
    // The runs of the slot's words every variant keeps (the server's, when it says).
    ...(id === 'clothing' ? { keep: ['open in the front'] } : {}),
    ...(id === 'woman' ? { person: {
      descent: { list: 'person.ethnicity', label: 'Descent', browse: 'region', parts: DESCENT, fits: DESCENT.flatMap(d => d.values),
        picked: { values: choice?.seeds?.descent?.values || [], groups: { region: choice?.seeds?.descent?.groups?.region || [] } },
        in_pool: Object.fromEntries(POOLS.woman.map(v => [v.seeds!.descent!, POOLS.woman.filter(x => x.seeds?.descent === v.seeds?.descent).length])) },
      gender: { list: 'person.gender', label: 'Gender', options: GENDERS, fits: ['woman', 'trans woman'],
        picked: { values: choice?.seeds?.gender?.values || [] }, in_pool: {} },
    } } : {}),
  }
}

axios.defaults.adapter = async (config: any) => {
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  const url = String(config.url).replace(/^.*\/prompt-programs\//, '')
  calls.push({ url, body })
  const ok = (data: any) => ({ data, status: 200, statusText: 'OK', headers: {}, config })
  if (url === 'suggest') return ok({ vary: [], adds: [] })
  if (url === 'prepare') {
    if (!/[<{]/.test(body.prompt || '')) return ok({ key: null, slots: [], choices: [] })
    const slots = SLOTS.filter(s => body.prompt.includes(`<${s.words}>`)).map(s => ({ ...s, state: held.has(s.id) ? 'writing' : 'ready' }))
    return ok({ key: 'k1', slots, choices: CHOICES.filter(c => !c.slot || slots.some(s => s.id === c.slot)), reading: slots.some(s => s.state !== 'ready'), working: slots.some(s => s.state !== 'ready') })
  }
  if (url === 'pools') {
    const choices: Record<string, ChoicePool> = Object.fromEntries(SLOTS.map(s => [s.id, poolFor(s.id, body.choices?.[s.id])]))
    choices.list1 = { options: ['summer', 'autumn', 'winter', 'spring'], more: false }
    return ok({ choices, more: Object.entries(choices).filter(([, p]) => p.more).map(([id]) => id) })
  }
  if (url === 'options') {
    await new Promise(r => setTimeout(r, moreMs.value))
    const have = new Set(POOLS[body.choice_id].map(v => v.text))
    const fresh = (body.choice_id === 'clothing' ? MORE : [`${POOLS[body.choice_id][0].text}, again`]).filter(t => !have.has(t))
    POOLS[body.choice_id].push(...fresh.map(text => ({ text })))
    return ok({ options: fresh })
  }
  return ok({})
}

// A thumbnail stands in for an image's.
const thumb = (media: number) => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="12" height="15"><rect width="12" height="15" fill="${media === 2 ? '#b5532a' : '#4a7dff'}"/></svg>`)}`

const prompt = ref((window as any).START ?? PROMPT)
const promptOptions = ref<any>({ autoImprove: { enabled: true, instructions: '', level: 'fill' } })
const pp = usePromptProgram({
  toolId: ref('local/krea-2'),
  prompt,
  enabled: computed(() => true),
  projectId: ref(null),
  promptOptions,
  setPromptOptions: (next: any) => { promptOptions.value = next },
  prepareWhenFound: () => true,
  thumbOf: thumb,
})

;(window as any).state = () => promptOptions.value.programChoices || {}
;(window as any).setState = (s: any) => { promptOptions.value = { ...promptOptions.value, programChoices: s } }
;(window as any).payload = () => pp.payload()
;(window as any).programStatus = () => pp.status.value
;(window as any).setPrompt = (p: string) => { prompt.value = p }
;(window as any).lookup = () => pp.lookup()

// Keep from this on an image's run record, from the image with this media id.
const keepOpen = ref<{ run: any; anchor: DOMRect; media?: number } | null>(null)
;(window as any).keep = (run: any, media = 2) => {
  keepOpen.value = { run, media, anchor: document.querySelector('[data-results]')!.getBoundingClientRect() }
}

createApp({
  render: () => h('div', { class: 'p-4 w-full max-w-[480px] flex flex-col gap-3' }, [
    h(AIPromptEditor, {
      modelValue: prompt.value,
      'onUpdate:modelValue': (v: string) => { prompt.value = v },
      promptOptions: promptOptions.value,
      'onUpdate:promptOptions': (v: any) => { promptOptions.value = v },
      programs: pp.status.value !== 'off',
      promptControl: true,
      externalChat: true,
      rows: 5,
      slotMarks: pp.marks.value,
      'onOpen-slot': (e: { n: number; words: string; rect: DOMRect }) => { if (pp.status.value !== 'off') pp.openEditorSlot(e) },
      'onOpen-list': (e: { n: number; rect: DOMRect }) => { if (pp.status.value !== 'off') pp.openEditorList(e) },
      'onSlot-hover': (e: { n: number; rect: DOMRect } | null) => { pp.hover.value = e },
    }, {
      mode: () => h('span', { class: 'text-ctl text-content' }, 'Fluent'),
      'below-editor': () => h(PromptSlotLines, { program: pp }),
    }),
    h('div', { 'data-results': '', class: 'h-10 rounded-md bg-surface-raised' }),
    h(FluentPicker, { program: pp }),
    h(PromptSlotHover, { program: pp }),
    h(KeepFromThisCard, { open: keepOpen.value, program: pp, onClose: () => { keepOpen.value = null } }),
  ]),
}).mount('#app')
