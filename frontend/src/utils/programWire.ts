/**
 * Fluent's wire shapes, in one place: what /prompt-programs/prepare and /prompt-programs/pools
 * answer, and what the user's choices look like when stored and sent.
 *
 * A slot is words in angle brackets in the prompt (`<young woman>`). Its value is a variant of
 * those words, written by the chat model in the background and kept as the slot's pool; each
 * slot is one choice, with the slot's id. A `{a|b}` list in the prompt is a choice with no slot.
 */

export type SlotKind = 'person' | 'animal' | 'camera' | 'light' | 'list' | 'free'

/** How a slot stands: `reading` (not read yet), `writing` (read; its first variants are being
    written), `ready` (a pool to draw from), `as_written` (its reading or its writer gave
    nothing: it stands as its words until the next prepare tries again). */
export type SlotState = 'reading' | 'writing' | 'ready' | 'as_written'

/** One slot of the prompt, as /prepare reads it. */
export interface ProgramSlot {
  id: string
  /** Its 1-based order in the prompt, as the editor counts slots. */
  n: number
  kind: SlotKind
  /** Two or three words for its line. */
  label: string
  /** The words between the brackets. */
  words: string
  /** Where it sits in the prompt as typed, brackets included; null when the prompt as read
      doesn't hold the same slots (a saved segment with slots of its own). */
  span?: [number, number] | null
  line?: number | null
  state?: SlotState
  /** Its id in the program the prepare named as shown (`from`), when it is the same slot there:
      what was chosen for it and its variants move over by this, not by the id. */
  was?: string
}

export interface ProgramChoice {
  id: string
  /** A slot's choice: the slot's id. None for a `{a|b}` list. */
  slot?: string
  /** `variants` for a slot, `pick` for the user's own list. */
  kind: 'variants' | 'pick'
  label: string
  /** The user's own `{a|b}` list. */
  source?: 'list'
  line?: number
  /** A list's options (a slot's come with /pools). */
  options?: string[]
  hidden?: boolean
  /** A `{a|b}` list's id in the program named by `from`, when it is the same list there. */
  was?: string
}

/** POST /prompt-programs/prepare. It answers at once from the prompt's parse: every slot,
    each with its state. A prompt with nothing that varies answers
    `{key: null, slots: [], choices: []}`; a format that isn't prepared
    `{key: null, unsupported: mode}`. */
export interface PreparedProgram {
  key: string | null
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  /** Some slot is still being read or written. */
  reading?: boolean
  /** Background work for this prompt is running now: look again soon. */
  working?: boolean
  /** The key of the program the request said it shows, when its slots' and lists' `was` say
      which of that program's parts they are. */
  from?: string
  /** Dev dialog only (include_program): what each part was read as, its picks, one draw. */
  readings?: unknown
  picks?: unknown
  example?: string
}

/** What /prepare answers, before it is known which of its forms this is. */
export type PrepareResponse = Partial<PreparedProgram> & { unsupported?: string }

/** The seeds a variant was written with: each only when given. */
export interface VariantSeeds {
  descent?: string
  gender?: string
  age?: string
  core?: string
  idea?: string
}

/** One variant in a slot's pool. A variant's identity is its text. */
export interface Variant {
  text: string
  seeds?: VariantSeeds
  uses?: number
  /** The user's own, added in the picker. */
  own?: boolean
}

/** Descent: a comprehensive list, browsed Region > heritage. */
export interface DescentPicker {
  list: string
  label: string
  /** The facet it is browsed by (`region`). */
  browse: string
  /** Every region, in the list's order, with its heritages. */
  parts: Array<{ id: string; values: string[] }>
  /** What the slot's words allow (all of it when they state no descent). */
  fits?: string[]
  picked?: { values: string[]; groups?: Record<string, string[]> }
  /** heritage -> how many variants in the pool carry it. */
  in_pool?: Record<string, number>
}

/** Gender: a short comprehensive list, shown whole, narrowed to what the words allow. */
export interface GenderPicker {
  list: string
  label: string
  options: string[]
  /** What the slot's words allow of it. */
  fits?: string[]
  picked?: { values: string[] }
  in_pool?: Record<string, number>
}

/** Age: browsed by life stage; each stage's › opens its single years. */
export interface AgePicker {
  list: string
  label: string
  /** The stage ids this person may be. */
  options: string[]
  stages: Array<{ id: string; label: string; span: [number, number]; years: number[] }>
  fits?: string[]
  picked?: { values: string[]; years?: number[] }
  in_pool?: Record<string, number>
  in_pool_years?: Record<string, number>
}

/** One choice's pool in /prompt-programs/pools. A slot's is its variants; a list's, its options. */
export interface ChoicePool {
  kind?: 'variants'
  state?: SlotState
  /** A write is in flight for this slot (a quiet spinner). */
  more?: boolean
  /** The whole pool in pool order (newest last), then the user's own. */
  variants?: Variant[]
  /** The same texts, for code that reads options; a list's options. */
  options: string[]
  /** The slot's choice as the server read it. */
  chosen?: ChoiceState | null
  /** The runs of the slot's words every variant keeps, when the server says. */
  keep?: string[]
  /** A person's comprehensive lists. */
  person?: { descent?: DescentPicker; gender?: GenderPicker; age?: AgePicker }
}

/** POST /prompt-programs/pools. `more`: the slots with a write in flight. */
export interface PoolsResponse { choices: Record<string, ChoicePool>; more?: string[] }

/** Seeds the user picked for a person: they steer the draw and the next writes. */
export interface ChoiceSeeds {
  descent?: { values?: string[]; groups?: { region?: string[] } }
  gender?: { values?: string[] }
  /** Life stage ids, and single years. */
  age?: { values?: string[]; years?: number[] }
}

/** What the user chose for one choice. Nothing chosen is no entry at all. */
export interface ChoiceState {
  /** Pinned variants (a list's options): the least-used of them is drawn. */
  values?: string[]
  /** The slot's own words, as they are. */
  as_written?: boolean
  /** Left out of the prompt (older choices; the picker no longer sets it). */
  off?: boolean
  seeds?: ChoiceSeeds
  /** The user's own variants (a list's own options). */
  add?: string[]
  /** Kept from an image (Keep from this): its media id, for its thumbnail. Never sent. */
  from?: number
}

/** "Any" is sent as no entry: the server reads `{any: true}` and nothing chosen the same. */

/** choice id -> what is chosen. Stored in promptOptions.programChoices and sent as
    promptOptions.program.choices. */
export type ProgramChoices = Record<string, ChoiceState>
