import { ref, computed, inject, isRef, type Ref, type ComputedRef, type InjectionKey } from 'vue'

// Provided by FlowView at the top of its subtree so every phase-tree row
// (PhaseNode, EquationTraceRow, IterationGroup, IterationCard) can resolve
// the current flow's chat scope without prop-drilling through four levels.
export const FLOW_CHAT_ID_KEY: InjectionKey<Ref<string | number | null>> =
  Symbol('flowChatId')

export function injectFlowChatIdRef(): Ref<string | number | null> {
  const r = inject(FLOW_CHAT_ID_KEY, null as unknown as Ref<string | number | null>)
  // Fall back to a dummy ref so call sites don't need to guard for the
  // injection-missing case (tests, standalone mounts).
  return r ?? ref<string | number | null>(null)
}

// Kinds match the granularities the flow UI exposes: a whole phase, a
// single equation / step, a collapsed iteration group, or one iteration.
// Inputs/Outputs cards are treated as phases for simplicity.
export type FlowRefKind = 'phase' | 'equation' | 'iteration-group' | 'iteration'

export interface FlowReference {
  kind: FlowRefKind
  // Stable key: `equation_key` for anything equation-rooted, a joined
  // phase_path for phase cards. Used for de-dup and as the attached-state
  // indicator on row buttons.
  refKey: string
  // Leaf name shown on the chip (the thing the user clicked).
  label: string
  // Parent label for context — e.g. the phase name for an equation. Empty
  // for top-level references.
  breadcrumb?: string
}

interface ChatBucket {
  items: Ref<FlowReference[]>
  hoveredRefKey: Ref<string | null>
}

// Module-scoped state so the phase tree and the chat composer (which live in
// separate component subtrees under FlowView) can share the same list
// without prop-drilling. Keyed by chatId because references are scoped to
// the conversation, not the flow — a flow can host multiple chats and
// each should carry its own pending context independently.
const buckets = new Map<string, ChatBucket>()

function bucketFor(chatId: string | number | null): ChatBucket {
  const key = chatId == null ? '' : String(chatId)
  let b = buckets.get(key)
  if (!b) {
    b = { items: ref<FlowReference[]>([]), hoveredRefKey: ref<string | null>(null) }
    buckets.set(key, b)
  }
  return b
}

export interface UseFlowReferences {
  items: ComputedRef<FlowReference[]>
  hoveredRefKey: ComputedRef<string | null>
  count: ComputedRef<number>
  has: (refKey: string) => boolean
  add: (ref: FlowReference) => void
  remove: (refKey: string) => void
  toggle: (ref: FlowReference) => void
  clear: () => void
  setHovered: (refKey: string | null) => void
}

// Accepts either a plain chatId or a Ref<chatId> so callers can either pin
// to a specific chat (e.g. sendMessage) or reactively follow a provided ref
// (e.g. phase-tree rows whose chat scope is set by FlowView after async
// load). Functions read the chatId lazily at call time so swaps mid-lifecycle
// route to the correct bucket.
type ChatIdArg = string | number | null | undefined | Ref<string | number | null>

export function useFlowReferences(chatIdArg: ChatIdArg): UseFlowReferences {
  const getId = (): string | number | null => {
    if (chatIdArg == null) return null
    if (isRef(chatIdArg)) return chatIdArg.value
    return chatIdArg
  }
  const getBucket = (): ChatBucket => bucketFor(getId())

  const items = computed<FlowReference[]>(() => getBucket().items.value)
  const hoveredRefKey = computed<string | null>(() => getBucket().hoveredRefKey.value)
  const count = computed<number>(() => items.value.length)

  function has(refKey: string): boolean {
    return getBucket().items.value.some((r) => r.refKey === refKey)
  }
  function add(r: FlowReference) {
    const b = getBucket()
    if (b.items.value.some((x) => x.refKey === r.refKey)) return
    b.items.value = [...b.items.value, r]
  }
  function remove(refKey: string) {
    const b = getBucket()
    b.items.value = b.items.value.filter((r) => r.refKey !== refKey)
    if (b.hoveredRefKey.value === refKey) b.hoveredRefKey.value = null
  }
  function toggle(r: FlowReference) {
    if (has(r.refKey)) remove(r.refKey)
    else add(r)
  }
  function clear() {
    const b = getBucket()
    b.items.value = []
    b.hoveredRefKey.value = null
  }
  function setHovered(refKey: string | null) {
    getBucket().hoveredRefKey.value = refKey
  }

  return { items, hoveredRefKey, count, has, add, remove, toggle, clear, setHovered }
}

// Serialize references into a blockquote header prepended to outgoing chat
// messages so the agent sees which flow items the user was pointing at.
// The chat display parses this header back into chips (see
// parseMessageReferences) so the raw markdown never appears in the user bubble
// — it's just a transport format the agent can read.
export function formatReferencesForMessage(refs: FlowReference[]): string {
  if (refs.length === 0) return ''
  const lines: string[] = ['> **Referring to:**']
  for (const r of refs) {
    lines.push(`> - ${refLineBody(r)}`)
  }
  return lines.join('\n')
}

function refLineBody(r: FlowReference): string {
  const kindLabel = kindToHeaderLabel(r.kind)
  const crumb = r.breadcrumb ? ` — in "${r.breadcrumb}"` : ''
  return `${kindLabel} · **${r.label}**${crumb} \`${r.refKey}\``
}

function kindToHeaderLabel(kind: FlowRefKind): string {
  switch (kind) {
    case 'phase': return 'Phase'
    case 'iteration-group': return 'Steps'
    case 'iteration': return 'Iteration'
    default: return 'Step'
  }
}

function headerLabelToKind(label: string): FlowRefKind {
  switch (label) {
    case 'Phase': return 'phase'
    case 'Steps': return 'iteration-group'
    case 'Iteration': return 'iteration'
    default: return 'equation'
  }
}

// Inverse of formatReferencesForMessage. The chat rendering calls this on the
// stored message_text so the blockquote header turns back into chip data, and
// the remaining body (minus the header + one blank separator) is what the
// user bubble actually displays as text.
export interface ParsedMessage {
  refs: FlowReference[]
  text: string
}

const REF_HEADER_LINE = /^> \*\*Referring to:\*\*\s*$/
const REF_ITEM_LINE = /^> - (Phase|Step|Steps|Iteration) · \*\*(.+?)\*\*(?: — in "(.+?)")? `(.+?)`\s*$/

export function parseMessageReferences(msg: string | null | undefined): ParsedMessage {
  const src = msg ?? ''
  if (!src) return { refs: [], text: '' }
  const lines = src.split('\n')
  if (lines.length === 0 || !REF_HEADER_LINE.test(lines[0])) {
    return { refs: [], text: src }
  }
  const refs: FlowReference[] = []
  let i = 1
  while (i < lines.length) {
    const m = REF_ITEM_LINE.exec(lines[i])
    if (!m) break
    const [, kindLabel, label, bread, refKey] = m
    refs.push({
      kind: headerLabelToKind(kindLabel),
      refKey,
      label,
      breadcrumb: bread || undefined,
    })
    i++
  }
  // Skip a single blank separator before the user-authored body, if present.
  if (lines[i] === '') i++
  const text = lines.slice(i).join('\n')
  return { refs, text }
}
