import { computed, createApp, h, ref } from 'vue'
import axios from 'axios'
import '../../src/style.css'
import PromptProgramChoices from '../../src/components/generation/PromptProgramChoices.vue'
import PromptProgramCard from '../../src/components/generation/PromptProgramCard.vue'
import { usePromptProgram } from '../../src/composables/usePromptProgram'
import type { ChoicePool, PreparedProgram, ProgramChoice, ProgramSlot } from '../../src/utils/programWire'

// The real composable and components, against a stand-in server that answers /prepare and
// /pools in the contract's shapes. `window.calls` records what was sent.

const words = (prefix: string, n: number) => Array.from({ length: n }, (_, i) => `${prefix} ${i + 1}`)
const PROMPT = 'dorm room with a <young man> and his <pet>, lit by <light>, {summer|autumn}'

const man: ProgramSlot = {
  id: 'young_man', n: 1, kind: 'person', label: 'Young man', words: 'young man', span: [17, 28], line: 1,
  details: ['young_man.age', 'young_man.descent', 'young_man.build', 'young_man.hair', 'young_man.outfit', 'young_man.outfit.colors'],
  stated: { age: 'young' },
}
const pet: ProgramSlot = { id: 'pet', n: 2, kind: 'free', label: 'Pet', words: 'pet', details: ['pet'] }
const light: ProgramSlot = { id: 'light', n: 3, kind: 'light', label: 'Light', words: 'light', details: ['light'] }
const cat: ProgramSlot = { id: 'cat', n: 4, kind: 'free', label: 'Cat', words: 'cat', details: ['cat'] }

const youngAges = ['18-year-old', '21-year-old', '24-year-old', '27-year-old']
const otherAges = ['35-year-old', '48-year-old', '62-year-old', '75-year-old']
const descents = ['Korean', 'Japanese', 'Chinese', 'Vietnamese', 'Indian', 'Iranian', 'Turkish', 'Nigerian', 'Kenyan', 'Irish',
  'Scottish', 'Welsh', 'English', 'French', 'German', 'Italian', 'Greek', 'Swedish', 'Mexican', 'Brazilian']
const hair = ['buzz cut', 'crew cut', 'side part', 'man bun', 'long waves', 'shoulder-length curls']
const outfits = ['a {main} flannel shirt and {neutral} jeans', 'a {main} hoodie and {neutral} joggers', 'a {main} suit with a {accent} tie']
const palettes = ['burgundy, cream and charcoal', 'navy, white and gray', 'olive, tan and black']
const lights = ['cool daylight entering through a tall window', 'a string of warm fairy lights tracing the bed frame', 'the glow of a laptop screen in a dark room']

const ch = (id: string, label: string, extra: Partial<ProgramChoice> = {}): ProgramChoice => ({ id, kind: 'pick', label, options: [], ...extra })
const choices: ProgramChoice[] = [
  ch('young_man.age', 'Age', { slot: 'young_man', cls: 'person.age_band', zones: [{ id: 'kinds', title: 'Young' }, { id: 'instead', title: 'Other ages' }] }),
  ch('young_man.descent', 'Descent', { slot: 'young_man', cls: 'person.ethnicity' }),
  ch('young_man.build', 'Build', { slot: 'young_man', cls: 'person.build', options: ['slim', 'stocky', 'athletic'] }),
  ch('young_man.hair', 'Hair', { slot: 'young_man', cls: 'person.hairstyle' }),
  ch('young_man.outfit', 'Outfit', { slot: 'young_man', cls: 'person.outfit.casual' }),
  ch('young_man.outfit.colors', 'Colors', { slot: 'young_man', cls: 'person.palette', follows: 'young_man.outfit' }),
  ch('pet', 'Pet', { slot: 'pet', options: ['pet', 'ginger tabby cat'], zones: [{ id: 'kinds', title: 'Kinds of pet' }, { id: 'instead', title: 'Instead of pet' }] }),
  ch('light', 'Light', { slot: 'light', options: lights }),
  ch('list1', 'Season', { source: 'list', line: 1, options: ['summer', 'autumn'] }),
]
const program = (slots: ProgramSlot[], extra: ProgramChoice[] = []): PreparedProgram => ({ key: `k${slots.length}`, slots, choices: [...choices, ...extra], example: '' })
const pools: Record<string, ChoicePool> = {
  'young_man.age': { options: [...youngAges, ...otherAges], zones: { kinds: youngAges, instead: otherAges } },
  'young_man.descent': { options: descents, groups: { region: { 'East Asian': descents.slice(0, 4), European: descents.slice(9, 18) } } },
  'young_man.build': { options: ['slim', 'stocky', 'athletic'] },
  'young_man.hair': { options: hair, groups: { length: { short: hair.slice(0, 3), long: hair.slice(3) }, style: { tied: ['man bun'] } } },
  'young_man.outfit': { options: outfits, short: { [outfits[0]]: 'flannel and jeans', [outfits[1]]: 'hoodie and joggers' } },
  'young_man.outfit.colors': { options: palettes },
  pet: { options: ['pet', 'ginger tabby cat', 'old basset hound', 'grey parrot', 'mug of coffee', 'stack of library books'],
    zones: { kinds: ['pet', 'ginger tabby cat', 'old basset hound', 'grey parrot'], instead: ['mug of coffee', 'stack of library books'] },
    short: { 'old basset hound': 'basset hound' } },
  light: { options: [...lights, ...words('lamp', 14)], short: { [lights[0]]: 'cool daylight', [lights[1]]: 'fairy lights', [lights[2]]: 'laptop glow' } },
  list1: { options: ['summer', 'autumn'] },
  cat: { options: ['cat', 'black cat', 'calico'], zones: { kinds: ['cat', 'black cat', 'calico'], instead: ['fox'] } },
}

const calls: Array<{ url: string; body: any }> = ((window as any).calls = [])
const prompt = ref(PROMPT)
// How long a model call takes here.
const prepareMs = ref(0)

axios.defaults.adapter = async (config: any) => {
  const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
  const url = String(config.url).replace(/^.*\/prompt-programs\//, '')
  calls.push({ url, body })
  const ok = (data: any) => ({ data, status: 200, statusText: 'OK', headers: {}, config })
  const withCat = body.prompt?.includes('<cat>')
  if (url === 'prepare') {
    if (body.cache_only && withCat) return ok({})
    if (!body.cache_only) await new Promise(r => setTimeout(r, prepareMs.value))
    return ok(withCat ? program([man, pet, light, cat], [ch('cat', 'Cat', { slot: 'cat', options: ['cat'], zones: [{ id: 'kinds', title: 'Kinds of cat' }, { id: 'instead', title: 'Instead of cat' }] })]) : program([man, pet, light]))
  }
  if (url === 'pools') return ok({ choices: pools })
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
// The editor made a slot: the prompt changes, and it asks for the slot's card.
;(window as any).newSlot = (ms: number) => {
  prepareMs.value = ms
  prompt.value = `${PROMPT} and a <cat>`
  const rect = document.querySelector('[data-editor]')!.getBoundingClientRect()
  pp.openEditorSlot({ n: 4, words: 'cat', rect })
}

createApp({
  render: () => h('div', { class: 'w-[520px] p-4' }, [
    h('div', { 'data-editor': '', class: 'h-16 rounded-md bg-surface-raised p-2 text-xs text-content' }, prompt.value),
    h(PromptProgramChoices, { program: pp }),
    h(PromptProgramCard, { program: pp }),
  ]),
}).mount('#app')
