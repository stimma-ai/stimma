import { computed, createApp, h, ref } from 'vue'
import '../../src/style.css'
import PromptProgramChoices from '../../src/components/generation/PromptProgramChoices.vue'
import { programSections } from '../../src/utils/programChoiceLayout'
import PromptProgramCard from '../../src/components/generation/PromptProgramCard.vue'
import type { ChoiceEdit, ChoiceVocab, ProgramChoice } from '../../src/composables/usePromptProgram'
import { isLimited, ticksOf, type TickState } from '../../src/utils/programTicks'
import { isOwnOption } from '../../src/utils/programAdditions'
import { standbyOf } from '../../src/utils/programVocab'

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
  { id: 'hair', kind: 'pick', label: 'Hair color', source: 'text', cls: 'person.hair_color', options: ['jet black', 'dark brown', 'ash brown', 'honey blonde', 'platinum blonde', 'salt and pepper'] },
  { id: 'face', kind: 'pick', label: 'Face', source: 'text', cls: 'person.face', options: words('face', 400) },
  { id: 'age', kind: 'pick', label: 'Age', source: 'text', cls: 'person.age_band', options: ['8–10-year-old', '20–24-year-old', '30–34-year-old', '40–44-year-old'] },
  // The user's own words ("a yellow ferrari"): every image uses them until others are ticked.
  { id: 'car', kind: 'pick', label: 'Car', source: 'text', said: 'yellow ferrari', options: ['yellow ferrari', 'red lamborghini', 'silver porsche'] },
]
for (const index of [1, 2]) {
  for (const label of ['Age', 'Ethnicity', 'Hairstyle', 'Expression']) {
    choices.push({ id: `friends[${index}].${label.toLowerCase()}`, kind: 'pick', label, source: 'added', group: 'friends', index, options: ['first', 'second'] })
  }
  choices.push(
    { id: `friends[${index}].hair`, kind: 'pick', label: 'Hair colour', source: 'added', group: 'friends', index, options: ['black', 'blonde'] },
    { id: `friends[${index}].outfit`, kind: 'pick', label: 'Outfit', source: 'added', group: 'friends', index, options: ['jacket', 'sweater'] },
    // Old prepared programs leave the palette outside the group; follows owns it.
    { id: `friends[${index}].outfit.colours`, kind: 'pick', label: 'Colours', source: 'text', follows: `friends[${index}].outfit`, options: ['navy and white', 'red and black'] },
  )
}
const groups = [{ id: 'friends', label: 'Friends', count: 2, source: 'text' }]
// 'a kept heritage': the user's own option, kept for the list from an earlier prompt.
const pools = ref<Record<string, string[]>>({ expression: Object.keys(expressionTiers), ethnicity: [...words('heritage', 20), 'a kept heritage'] })
const vocab = ref<Record<string, ChoiceVocab>>({
  expression: { cls: 'person.expression', label: 'Expression', closed: false, tiers: expressionTiers },
  ethnicity: { cls: 'person.ethnicity', label: 'Ethnicity', closed: true, tiers: Object.fromEntries([...words('heritage', 20), 'a kept heritage'].map(v => [v, 'typical' as const])), mine: ['a kept heritage'] },
  hair: {
    cls: 'person.hair_color', label: 'Hair color', closed: true, tiers: {},
    // "salt and pepper" belongs to more than one part, so it has none here.
    parts: { name: 'shade', values: ['black', 'brunette', 'strawberry_blonde'], of: { 'jet black': 'black', 'dark brown': 'brunette', 'ash brown': 'brunette', 'honey blonde': 'strawberry_blonde', 'platinum blonde': 'strawberry_blonde' } },
  },
  face: { cls: 'person.face', label: 'Face', closed: true, tiers: {} },
  age: { cls: 'person.age_band', label: 'Age', closed: true, tiers: { '8–10-year-old': 'opt_in', '20–24-year-old': 'typical', '30–34-year-old': 'typical', '40–44-year-old': 'plausible' } },
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

const ticks = (c: ProgramChoice) => ticksOf(c, pins.value[c.id], edits.value[c.id], optionsOf(c), standbyOf(vocab.value[c.id]))
const changed = (c: ProgramChoice) => isLimited(c, pins.value[c.id], edits.value[c.id], optionsOf(c), standbyOf(vocab.value[c.id]))
function cleanEdit(edit: ChoiceEdit): ChoiceEdit {
  const out: ChoiceEdit = {}
  if (edit.add?.length) out.add = edit.add
  if (edit.remove?.length) out.remove = edit.remove
  if (edit.off) out.off = true
  if (edit.out?.length) out.out = edit.out
  if (edit.none) out.none = true
  return out
}

const program = {
  program: ref({ key: 'k', choices, groups, params: {}, loras: [], lora_choices: {}, example: '' }),
  status: ref('ready'),
  sections: computed(() => programSections(choices, groups)),
  open: (id: string, anchor: Element) => { openCard.value = { id, anchor: anchor.getBoundingClientRect() } },
  choices: computed(() => choices),
  byId: computed(() => Object.fromEntries(choices.map(c => [c.id, c]))),
  pins, edits, openCard,
  optionsOf,
  vocabOf: (c: ProgramChoice) => vocab.value[c.id] || null,
  setPins: (id: string, values: string[]) => { pins.value = { ...pins.value, [id]: values } },
  setManyPins: (values: Record<string, string[]>) => { pins.value = { ...pins.value, ...values } },
  setEdit: (id: string, edit: ChoiceEdit) => { edits.value = { ...edits.value, [id]: cleanEdit(edit) } },
  setTicks: (id: string, state: TickState, edit: ChoiceEdit = edits.value[id] || {}) => {
    pins.value = { ...pins.value, [id]: state.pins }
    edits.value = { ...edits.value, [id]: cleanEdit({ ...edit, out: state.out, none: state.none }) }
  },
  isPinned: (c: ProgramChoice) => changed(c) && ticks(c).size > 0,
  isNone: (c: ProgramChoice) => changed(c) && !ticks(c).size,
  showsValue: (c: ProgramChoice) => !!c.said || (changed(c) && ticks(c).size > 0),
  valueText: (c: ProgramChoice) => {
    const t = [...ticks(c)]
    return t.length === 1 ? t[0] : `${t.length} of ${optionsOf(c).length}`
  },
  suggestOptions: async (c: ProgramChoice, mode: string) => { calls.push({ suggest: c.id, mode }) },
  isOwn: (c: ProgramChoice, o: string) => isOwnOption(o, edits.value[c.id], vocab.value[c.id]),
  keepAddition: async (c: ProgramChoice, text: string, keep = true) => { calls.push({ [keep ? 'keep' : 'forget']: text, cls: c.cls }) },
  close: () => { openCard.value = null },
}

;(window as any).openChoice = (id: string | null) => { openCard.value = id ? { id, anchor: new DOMRect(20, 20, 80, 24) } : null }
;(window as any).state = () => ({ pins: pins.value, edits: edits.value, calls })
let escapes = 0
window.addEventListener('keydown', e => { if (e.key === 'Escape') escapes++ })
;(window as any).escapes = () => escapes

createApp({ render: () => h('div', { class: 'w-full' }, [h(PromptProgramChoices, { program: program as any }), h(PromptProgramCard, { program: program as any })]) }).mount('#app')
