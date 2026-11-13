import { computed, createApp, h, ref } from 'vue'
import axios from 'axios'
import '../../src/style.css'
import PromptProgramChoices from '../../src/components/generation/PromptProgramChoices.vue'
import PromptProgramCard from '../../src/components/generation/PromptProgramCard.vue'
import KeepFromThisCard from '../../src/components/generation/KeepFromThisCard.vue'
import { usePromptProgram } from '../../src/composables/usePromptProgram'
import type { ChoicePool, PreparedProgram, ProgramChoice, ProgramSlot } from '../../src/utils/programWire'

// The real composable and components, against a stand-in server that answers /prepare and
// /pools in the shapes the routes give (routes/prompt_programs.py): a slot's span holds its
// brackets, a bound pick names its list and tiers, a list's declared groups are the facet
// "group". The base prompt is read; a slot added to it is `reading` until a prepare that isn't
// cache-only reads it, in the background (`working`). `window.calls` records what was sent.

const words = (prefix: string, n: number) => Array.from({ length: n }, (_, i) => `${prefix} ${i + 1}`)
const PROMPT = 'dorm room with a <young man> and his <pet>, lit by <light>, {summer|autumn}'

const man: ProgramSlot = {
  id: 'young_man', n: 1, kind: 'person', label: 'Young man', words: 'young man', span: [17, 28], line: 1,
  details: ['young_man.age', 'young_man.descent', 'young_man.build', 'young_man.hair', 'young_man.face', 'young_man.face.eyes',
    'young_man.face.nose', 'young_man.outfit', 'young_man.outfit.colors'],
  stated: { age: 'young' },
}
const pet: ProgramSlot = { id: 'pet', n: 2, kind: 'free', label: 'Pet', words: 'pet', span: [37, 42], line: 1, details: ['pet'] }
const light: ProgramSlot = { id: 'light', n: 3, kind: 'light', label: 'Light', words: 'light', span: [51, 58], line: 1, details: ['light'] }
// A slot just typed, read before the editor's text caught up: no span yet.
const cat: ProgramSlot = { id: 'cat', n: 4, kind: 'free', label: 'Cat', words: 'cat', span: null, line: null, details: ['cat'] }

const youngAges = ['18-year-old', '21-year-old', '24-year-old', '27-year-old']
const otherAges = ['35-year-old', '48-year-old', '62-year-old', '75-year-old']
const descents = ['Korean', 'Japanese', 'Chinese', 'Vietnamese', 'Indian', 'Iranian', 'Turkish', 'Nigerian', 'Kenyan', 'Irish',
  'Scottish', 'Welsh', 'English', 'French', 'German', 'Italian', 'Greek', 'Swedish', 'Mexican', 'Brazilian']
const hair = ['buzz cut', 'crew cut', 'side part', 'man bun', 'long waves', 'shoulder-length curls']
const outfits = ['a {main} flannel shirt and {neutral} jeans', 'a {main} hoodie and {neutral} joggers', 'a {main} suit with a {accent} tie']
const palettes = ['burgundy, cream and charcoal', 'navy, white and gray', 'olive, tan and black']
// A face is its parts (routes: `part_of`), each its own list with "nothing notable" first.
const faces = ['gently almond-shaped eyes', 'a slightly small nose']
const eyes = ['evenly set eyes of average size', 'gently almond-shaped eyes', 'slightly rounded eyes', 'monolid eyes']
const noses = ['a nose of average size and shape', 'a slightly small nose', 'a softly rounded nose tip', 'a broad nose']
const lights = ['cool daylight entering through a tall window', 'a string of warm fairy lights tracing the bed frame', 'the glow of a laptop screen in a dark room']

const ch = (id: string, label: string, extra: Partial<ProgramChoice> = {}): ProgramChoice => ({ id, kind: 'pick', label, options: [], ...extra })
const choices: ProgramChoice[] = [
  ch('young_man.age', 'Age', { slot: 'young_man', cls: 'person.age_band', options: [...youngAges, ...otherAges], zones: [{ id: 'kinds', title: 'Young' }, { id: 'instead', title: 'Instead of young' }] }),
  ch('young_man.descent', 'Descent', { slot: 'young_man', cls: 'person.ethnicity', options: descents }),
  ch('young_man.build', 'Build', { slot: 'young_man', cls: 'person.build', options: ['slim', 'stocky', 'athletic'] }),
  ch('young_man.hair', 'Hair', { slot: 'young_man', cls: 'person.hairstyle', options: hair }),
  ch('young_man.face', 'Face', { slot: 'young_man', cls: 'person.face', options: faces, starts_off: true }),
  ch('young_man.face.eyes', 'Eye shape', { slot: 'young_man', cls: 'person.feature.eyes', options: eyes.slice(0, 3), starts_off: true, part_of: 'young_man.face' }),
  ch('young_man.face.nose', 'Nose', { slot: 'young_man', cls: 'person.feature.nose', options: noses.slice(0, 3), starts_off: true, part_of: 'young_man.face' }),
  ch('young_man.outfit', 'Outfit', { slot: 'young_man', cls: 'person.outfit.casual', options: outfits }),
  ch('young_man.outfit.colors', 'Colors', { slot: 'young_man', cls: 'person.palette', options: palettes, follows: 'young_man.outfit' }),
  ch('pet', 'Pet', { slot: 'pet', options: ['pet', 'ginger tabby cat'], zones: [{ id: 'kinds', title: 'Kinds of pet' }, { id: 'instead', title: 'Instead of pet' }] }),
  ch('light', 'Light', { slot: 'light', options: lights }),
  ch('list1', 'Season', { source: 'list', line: 1, options: ['summer', 'autumn'] }),
]
const program = (slots: ProgramSlot[], extra: ProgramChoice[] = []): PreparedProgram => ({ key: `k${slots.length}`, slots, choices: [...choices, ...extra], example: '' })
// What /pools says of a choice bound to a vocabulary list.
const bound = (cls: string, label: string, options: string[], extra: Partial<ChoicePool> = {}): ChoicePool => ({
  options, more: false, cls, label, closed: true, tiers: Object.fromEntries(options.map(o => [o, 'typical'])), ...extra,
})
const pools: Record<string, ChoicePool> = {
  'young_man.age': bound('person.age_band', 'Age', [...youngAges, ...otherAges], { zones: { kinds: youngAges, instead: otherAges } }),
  'young_man.descent': bound('person.ethnicity', 'Descent', descents, { groups: { group: { 'East Asian': descents.slice(0, 4), European: descents.slice(9, 18) } } }),
  'young_man.build': bound('person.build', 'Build', ['slim', 'stocky', 'athletic']),
  'young_man.hair': bound('person.hairstyle', 'Hairstyle', hair, { groups: { length: { short: hair.slice(0, 3), long: hair.slice(3) }, style: { tied: ['man bun'] } } }),
  'young_man.face.eyes': bound('person.feature.eyes', 'Eye shape', eyes, { short: { [eyes[0]]: 'nothing notable', [eyes[1]]: 'almond eyes' }, groups: { aspect: { shape: eyes.slice(1, 3), lids: [eyes[3]] } } }),
  'young_man.face.nose': bound('person.feature.nose', 'Nose', noses, { short: { [noses[0]]: 'nothing notable', [noses[1]]: 'small nose' }, groups: { aspect: { size: [noses[1], noses[3]], tip: [noses[2]] } } }),
  'young_man.outfit': bound('person.outfit.casual', 'Outfit', outfits, { short: { [outfits[0]]: 'flannel and jeans', [outfits[1]]: 'hoodie and joggers' } }),
  'young_man.outfit.colors': bound('person.palette', 'Palette', palettes),
  pet: { options: ['pet', 'ginger tabby cat', 'old basset hound', 'gray parrot'], more: false,
    zones: { kinds: ['pet', 'ginger tabby cat', 'old basset hound', 'gray parrot'], instead: ['mug of coffee', 'stack of library books'] },
    short: { 'old basset hound': 'basset hound' } },
  light: { options: [...lights, ...words('lamp', 14)], more: false, short: { [lights[0]]: 'cool daylight', [lights[1]]: 'fairy lights', [lights[2]]: 'laptop glow' } },
  list1: { options: ['summer', 'autumn'], more: false },
  cat: { options: ['cat', 'black cat', 'calico'], more: false, zones: { kinds: ['cat', 'black cat', 'calico'], instead: ['fox'] } },
}

const calls: Array<{ url: string; body: any }> = ((window as any).calls = [])
const prompt = ref(PROMPT)
// How long a model call takes here.
const prepareMs = ref(0)
// How long a cache-only look-up takes to come back (its answer is what the server had when asked).
const lookupMs = ref(0)
// <cat> and <broken>: 'working' while the server reads them, then 'read'.
const reads = new Map<string, 'working' | 'read'>()
const unread = (slot: ProgramSlot): ProgramSlot => ({ ...slot, kind: 'free', label: slot.words, details: [], state: 'reading' })
// An animal with only its breed varying: a builder of one detail.
const dog: ProgramSlot = { id: 'dog', n: 4, kind: 'animal', label: 'Dog', words: 'dog', span: null, line: 1, details: ['dog.breed'] }
const breeds = ['beagle', 'border collie', 'dachshund']
const dogBreed = ch('dog.breed', 'Dog breed', { slot: 'dog', cls: 'animal.dog_breed', options: breeds })
// An outfit list slot: one row, its colors inside it.
const outfitSlot: ProgramSlot = { id: 'outfit', n: 5, kind: 'list', label: 'Outfit', words: 'outfit', span: null, line: 1, details: ['outfit', 'outfit.colors'] }
const outfitList = [ch('outfit', 'Outfit', { slot: 'outfit', cls: 'person.outfit.casual', options: outfits }),
  ch('outfit.colors', 'Colors', { slot: 'outfit', cls: 'person.palette', options: palettes, follows: 'outfit' })]
const broken: ProgramSlot = { id: 'broken', n: 1, kind: 'free', label: 'broken', words: 'broken', span: [2, 10], line: 1, details: [] }

axios.defaults.adapter = async (config: any) => {
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  const url = String(config.url).replace(/^.*\/prompt-programs\//, '')
  calls.push({ url, body })
  const ok = (data: any) => ({ data, status: 200, statusText: 'OK', headers: {}, config })
  const withCat = body.prompt?.includes('<cat>')
  if (url === 'prepare') {
    // A prompt with nothing in it that varies has no program, and is no error.
    if (!/[<{]/.test(body.prompt || '')) return ok({ key: null, slots: [], choices: [] })
    if (body.prompt?.includes('<broken>')) {
      if (body.cache_only) return ok({ key: 'kb', slots: [unread(broken)], choices: [], reading: true, working: false })
      const e: any = new Error('424')
      e.response = { status: 424, data: { detail: { code: 'reader_failed', message: 'The chat model’s reading of this prompt couldn’t be used.' } } }
      throw e
    }
    if (body.prompt?.includes('<dog>')) return ok(program([man, pet, light, dog, outfitSlot], [dogBreed, ...outfitList]))
    if (!withCat) return ok(program([man, pet, light]))
    if (!body.cache_only && !reads.has('cat')) {
      reads.set('cat', 'working')
      setTimeout(() => reads.set('cat', 'read'), prepareMs.value)
    }
    const late = async (data: any) => { if (body.cache_only && lookupMs.value) await new Promise(r => setTimeout(r, lookupMs.value)); return ok(data) }
    if (reads.get('cat') !== 'read') return late({ ...program([man, pet, light, unread(cat)]), reading: true, working: reads.get('cat') === 'working' })
    return late(program([man, pet, light, cat], [ch('cat', 'Cat', { slot: 'cat', options: ['cat'], zones: [{ id: 'kinds', title: 'Kinds of cat' }, { id: 'instead', title: 'Instead of cat' }] })]))
  }
  if (url === 'pools') {
    const have = new Set((withCat ? [...choices, { id: 'cat' }] : choices).map(c => c.id))
    const dogs = body.prompt?.includes('<dog>') ? { 'dog.breed': bound('animal.dog_breed', 'Dog breed', breeds),
      outfit: bound('person.outfit.casual', 'Outfit', outfits), 'outfit.colors': bound('person.palette', 'Palette', palettes) } : {}
    return ok({ choices: { ...Object.fromEntries(Object.entries(pools).filter(([id]) => have.has(id))), ...dogs }, more: [] })
  }
  if (url === 'options') return ok({ options: ['three-legged greyhound', 'sleepy ferret'] })
  return ok({})
}

const promptOptions = ref<any>({})
const pp = usePromptProgram({
  toolId: ref('tool'),
  prompt,
  enabled: computed(() => true),
  projectId: ref(null),
  promptOptions,
  setPromptOptions: (next: any) => { promptOptions.value = next },
  prepareWhenFound: () => true,
})

;(window as any).state = () => promptOptions.value.programChoices || {}
;(window as any).setState = (s: any) => { promptOptions.value = { ...promptOptions.value, programChoices: s } }
;(window as any).payload = () => pp.payload()
;(window as any).programStatus = () => pp.status.value
;(window as any).programError = () => pp.error.value
;(window as any).setPrompt = (p: string) => { prompt.value = p }
;(window as any).slow = (lookup: number, read: number) => { lookupMs.value = lookup; prepareMs.value = read }
;(window as any).prepare = () => { void pp.prepare() }
// The editor made a slot: the prompt changes, and it asks for the slot's card.
;(window as any).newSlot = (ms: number) => {
  prepareMs.value = ms
  prompt.value = `${PROMPT} and a <cat>`
  const rect = document.querySelector('[data-editor]')!.getBoundingClientRect()
  pp.openEditorSlot({ n: 4, words: 'cat', rect })
}

// Keep from this, opened on an image's run record (`prompt_program` in its job's parameters).
const keepOpen = ref<{ run: any; anchor: DOMRect } | null>(null)
;(window as any).keep = (run: any) => {
  keepOpen.value = { run, anchor: document.querySelector('[data-editor]')!.getBoundingClientRect() }
}

createApp({
  render: () => h('div', { class: 'w-[520px] p-4' }, [
    h(KeepFromThisCard, { open: keepOpen.value, program: pp, onClose: () => { keepOpen.value = null } }),
    h('div', { 'data-editor': '', class: 'h-16 rounded-md bg-surface-raised p-2 text-xs text-content' }, prompt.value),
    h(PromptProgramChoices, { program: pp }),
    h(PromptProgramCard, { program: pp }),
  ]),
}).mount('#app')
