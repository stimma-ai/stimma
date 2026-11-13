/**
 * Fluent's wire shapes, in one place: what /prompt-programs/prepare and /prompt-programs/pools
 * answer, and what the user's choices look like when stored and sent.
 *
 * A slot is words in angle brackets in the prompt (`<young man>`). Each slot has one or more
 * choices: a person or camera slot one per detail (age, hair, outfit, its colors…), any other
 * slot exactly one. A `{a|b}` list in the prompt is a choice with no slot.
 */

import type { VocabTier } from './programVocab.ts'

export type SlotKind = 'person' | 'animal' | 'camera' | 'light' | 'list' | 'free'

/** One slot of the prompt, as /prepare reads it. */
export interface ProgramSlot {
  id: string
  /** Its 1-based order in the prompt, as the editor counts slots. */
  n: number
  kind: SlotKind
  /** Two or three words for its pill. */
  label: string
  /** The words between the brackets. */
  words: string
  /** Where it sits in the prompt as typed, brackets included; null when the prompt as read
      doesn't hold the same slots (a saved segment with slots of its own). */
  span?: [number, number] | null
  line?: number | null
  /** Its choices' ids, in the order the builder lists them. */
  details: string[]
  /** For a person: detail -> the slot's own words that settle it ({age: "elderly"}). */
  stated?: Record<string, string>
  /** `reading` until the slot reader has said what it is (it shows its words and nothing to
      choose yet), then `ready`. */
  state?: 'reading' | 'ready'
  /** Its reading couldn't be used: it stands as its words until it is read again. */
  degraded?: boolean
  /** Its id in the program the prepare named as shown (`from`), when it is the same slot there:
      what was chosen for it and its options move over by this, not by the id. */
  was?: string
}

/** A choice's zone: where its options come from. `kinds` (kinds of what the words name) is
    the default; `instead` holds other things that could stand there. */
export interface ChoiceZone { id: string; title?: string }

export interface ProgramChoice {
  id: string
  /** The slot it belongs to; none for a `{a|b}` list. */
  slot?: string
  kind: 'pick'
  label: string
  /** The user's own `{a|b}` list. */
  source?: 'list'
  line?: number
  /** The vocabulary list it draws from. */
  cls?: string
  /** Its options as prepared (a zone's options arrive with /pools). */
  options: string[]
  zones?: ChoiceZone[]
  hidden?: boolean
  /** Drawn to go with another choice (an outfit's colors). */
  follows?: string
  /** Left out until the user turns it on (a person's face). */
  starts_off?: boolean
  /** A part of another choice (a face's nose): listed inside that choice, not beside it. */
  part_of?: string
  parent?: string
  when?: string[]
  /** A `{a|b}` list's id in the program named by `from`, when it is the same list there. */
  was?: string
}

/** POST /prompt-programs/prepare. It answers at once from the prompt's parse: every slot,
    each still `reading` or `ready`. A prompt with nothing that varies answers
    `{key: null, slots: [], choices: []}`; a format that isn't prepared
    `{key: null, unsupported: mode}`. */
export interface PreparedProgram {
  key: string | null
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  /** Some part is still being read (or narrowed). */
  reading?: boolean
  /** Background reading for this prompt is running now: look again soon. */
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

/** One choice's options in /prompt-programs/pools. A choice bound to a vocabulary list also
    says which list (`cls`, `label`, `closed`) and each option's tier. */
export interface ChoicePool {
  options: string[]
  /** zone id -> its options. */
  zones?: Record<string, string[]>
  /** facet -> part -> its options. An option may sit in several parts. The facet `group`
      holds the list's declared groups (descent's heritages). */
  groups?: Record<string, Record<string, string[]>>
  cls?: string
  label?: string
  closed?: boolean
  tiers?: Record<string, VocabTier>
  /** The user's own options kept for this choice's list from earlier prompts. */
  mine?: string[]
  /** Its options are still being written. */
  more?: boolean
  /** option -> its short form, for pills and rows, where one exists. */
  short?: Record<string, string>
  /** option -> one line on what it looks like, for lists that teach (hairstyles, film stocks). */
  looks?: Record<string, string>
}

/** POST /prompt-programs/pools. `more`: the choices whose options are still being written. */
export interface PoolsResponse { choices: Record<string, ChoicePool>; more?: string[] }

/** What the user chose for one choice. Nothing chosen is no entry at all. */
export interface ChoiceState {
  /** Option texts. */
  values?: string[]
  /** facet -> parts: every option in those parts. */
  groups?: Record<string, string[]>
  /** Zone ids: every option in those zones. */
  zones?: string[]
  /** Left out of the prompt. */
  off?: boolean
  /** Drawn, for a choice that starts left out (`starts_off`). */
  on?: boolean
  /** The user's own options. */
  add?: string[]
}

/** "Any" is sent as no entry: the server reads `{any: true}` and nothing chosen the same. */

/** choice id -> what is chosen. Stored in promptOptions.programChoices and sent as
    promptOptions.program.choices. */
export type ProgramChoices = Record<string, ChoiceState>
