/**
 * Fluent's wire shapes, in one place: what /prompt-programs/prepare and /prompt-programs/pools
 * answer, and what the user's choices look like when stored and sent.
 *
 * A slot is words in angle brackets in the prompt (`<young man>`). Each slot has one or more
 * choices: a person or camera slot one per detail (age, hair, outfit, its colors…), any other
 * slot exactly one. A `{a|b}` list in the prompt is a choice with no slot.
 */

import type { VocabTier } from './programVocab.ts'

export type SlotKind = 'person' | 'camera' | 'light' | 'list' | 'free'

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
  span?: [number, number]
  line?: number
  /** Its choices' ids, in the order the builder lists them. */
  details: string[]
  /** For a person: detail -> the slot's own words that settle it ({age: "elderly"}). */
  stated?: Record<string, string>
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
  parent?: string
  when?: string[]
}

/** POST /prompt-programs/prepare */
export interface PreparedProgram {
  key: string
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  example?: string
  seconds?: number
  /** Dev dialog only (include_program). */
  program?: string
  enhanced?: string
  unsupported?: boolean
}

/** One choice's options in /prompt-programs/pools. */
export interface ChoicePool {
  options: string[]
  /** zone id -> its options. */
  zones?: Record<string, string[]>
  /** facet -> part -> its options. An option may sit in several parts. */
  groups?: Record<string, Record<string, string[]>>
  tiers?: Record<string, VocabTier>
  /** The user's own options kept for this choice's list from earlier prompts. */
  mine?: string[]
  /** Its options are still being written. */
  more?: boolean
  /** option -> its short form, for pills and rows, where one exists. */
  short?: Record<string, string>
}

/** POST /prompt-programs/pools */
export interface PoolsResponse { choices: Record<string, ChoicePool> }

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
  /** The user's own options. */
  add?: string[]
}

/** choice id -> what is chosen. Stored in promptOptions.programChoices and sent as
    promptOptions.program.choices. */
export type ProgramChoices = Record<string, ChoiceState>
