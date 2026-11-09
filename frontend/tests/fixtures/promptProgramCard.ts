import { computed, createApp, h, ref } from 'vue'
import '../../src/style.css'
import PromptProgramCard from '../../src/components/generation/PromptProgramCard.vue'
import type { ChoiceEdit, ChoiceVocab, ProgramChoice } from '../../src/composables/usePromptProgram'

// A stand-in for usePromptProgram: just the state the choice card reads and writes.
const words = (prefix: string, n: number) => Array.from({ length: n }, (_, i) => `${prefix} ${i + 1}`)
const expressionTiers: Record<string, ChoiceVocab['tiers'][string]> = {}
for (const v of words('soft smile', 10)) expressionTiers[v] = 'typical'
for (const v of words('wry frown', 8)) expressionTiers[v] = 'plausible'
for (const v of words('odd squint', 6)) expressionTiers[v] = 'unusual'
const generated = words('new grimace', 5)
for (const v of generated) expressionTiers[v] = 'generated'

const choices: ProgramChoice[] = [
  { id: 'expression', kind: 'pick', label: 'Expression', source: 'text', cls: 'person.expression', options: Object.keys(expressionTiers).filter(v => !generated.includes(v)) },
  { id: 'ethnicity', kind: 'pick', label: 'Ethnicity', source: 'text', cls: 'person.ethnicity', options: words('heritage', 20) },
  { id: 'color', kind: 'pick', label: 'Color', source: 'text', options: words('shade', 15) },
  { id: 'mood', kind: 'pick', label: 'Mood', source: 'text', options: ['calm', 'tense', 'joyful', 'wistful'] },
]
const pools = ref<Record<string, string[]>>({ expression: Object.keys(expressionTiers), ethnicity: words('heritage', 20) })
const vocab = ref<Record<string, ChoiceVocab>>({
  expression: { cls: 'person.expression', label: 'Expression', closed: false, tiers: expressionTiers },
  ethnicity: { cls: 'person.ethnicity', label: 'Ethnicity', closed: true, tiers: Object.fromEntries(words('heritage', 20).map(v => [v, 'typical' as const])) },
})
const pins = ref<Record<string, string[]>>({})
const edits = ref<Record<string, ChoiceEdit>>({})
const openCard = ref<{ id: string; anchor: DOMRect } | null>(null)
const calls: any[] = ((window as any).calls = [])

function optionsOf(c: ProgramChoice): string[] {
  const e = edits.value[c.id] || {}
  const removed = new Set(e.remove || [])
  const base = [...new Set([...c.options, ...(pools.value[c.id] || [])])]
  return [...base.filter(x => !removed.has(x)), ...(e.add || []).filter(x => !base.includes(x))]
}

const program = {
  program: ref({ key: 'k', choices, groups: [], params: {}, loras: [], lora_choices: {}, example: '' }),
  choices: computed(() => choices),
  byId: computed(() => Object.fromEntries(choices.map(c => [c.id, c]))),
  pins, edits, openCard,
  optionsOf,
  vocabOf: (c: ProgramChoice) => vocab.value[c.id] || null,
  setPins: (id: string, values: string[]) => { pins.value = { ...pins.value, [id]: values } },
  setManyPins: (values: Record<string, string[]>) => { pins.value = { ...pins.value, ...values } },
  setEdit: (id: string, edit: ChoiceEdit) => { edits.value = { ...edits.value, [id]: edit } },
  isPinned: (c: ProgramChoice) => (pins.value[c.id] || []).length > 0,
  valueText: (c: ProgramChoice) => `${optionsOf(c).length} options`,
  suggestOptions: async (c: ProgramChoice, mode: string) => { calls.push({ suggest: c.id, mode }) },
  close: () => { openCard.value = null },
}

;(window as any).openChoice = (id: string) => { openCard.value = { id, anchor: new DOMRect(20, 20, 80, 24) } }
;(window as any).state = () => ({ pins: pins.value, edits: edits.value })
let escapes = 0
window.addEventListener('keydown', e => { if (e.key === 'Escape') escapes++ })
;(window as any).escapes = () => escapes

createApp({ render: () => h(PromptProgramCard, { program: program as any }) }).mount('#app')
