<template>
  <!-- One version of the prompt: a plain block, as it always was. -->
  <PromptBlock v-if="stages.length < 2" :text="last?.text ?? null" :label="label" />

  <!-- Several: what the user wrote, the prompt filled in for this image, and what
       the model got, on a small rail. The last is always shown whole; an earlier
       one is a single line until its header opens it. -->
  <div v-else data-testid="prompt-stages">
    <div v-if="label" class="mb-1 text-xs text-content-tertiary">{{ label }}</div>
    <div class="relative pl-3.5">
      <div
        v-for="(stage, i) in stages"
        :key="stage.key"
        class="group relative"
        :class="i < stages.length - 1 ? 'pb-2' : ''"
        :data-stage="stage.key"
      >
        <span
          class="absolute -left-3.5 top-[7px] w-[5px] h-[5px] rounded-full"
          :class="stage.final ? 'bg-accent-hi' : 'bg-edge-strong'"
        ></span>
        <span
          v-if="i < stages.length - 1"
          class="absolute -left-[12px] top-[16px] bottom-0 w-px bg-edge-strong"
        ></span>

        <div class="flex items-center justify-between gap-2 min-h-[22px]">
          <button
            v-if="!stage.final"
            type="button"
            class="inline-flex items-center gap-1 -ml-1 px-1 rounded bg-transparent border-none text-xs text-content-tertiary cursor-pointer hover:text-content hover:bg-overlay-subtle transition-colors duration-100"
            :aria-expanded="isOpen(stage.key)"
            @click="toggle(stage.key)"
          >
            {{ stage.label }}
            <ChevronRightIcon class="w-3 h-3 transition-transform duration-150" :class="isOpen(stage.key) ? 'rotate-90' : ''" />
          </button>
          <span v-else class="text-xs text-content-tertiary">
            {{ stage.label }}<span v-if="stage.note" class="text-content-muted"> · {{ stage.note }}</span>
          </span>
          <Tip v-if="host.copy" text="Copy">
            <IconButton
              aria-label="Copy"
              class="!w-6 !h-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
              @click="copy(stage.text)"
            >
              <ClipboardDocumentIcon class="w-3.5 h-3.5" />
            </IconButton>
          </Tip>
        </div>

        <p
          class="m-0 text-xs leading-relaxed break-words select-text"
          :class="[
            stage.final ? 'text-content' : 'text-content-secondary',
            stage.final || isOpen(stage.key) ? 'whitespace-pre-wrap' : 'whitespace-nowrap overflow-hidden text-ellipsis',
          ]"
          @click="copyOnClick(stage.text)"
        ><span
          v-for="(piece, j) in stage.pieces"
          :key="j"
          :class="piece.cls"
          :title="piece.title"
          :data-syntax="piece.syntax"
        >{{ piece.text }}</span></p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronRightIcon, ClipboardDocumentIcon } from '@heroicons/vue/24/outline'
import IconButton from '../components/ui/IconButton.vue'
import PromptBlock from './PromptBlock.vue'
import Tip from './Tip.vue'
import { useProvenanceHost } from './host.ts'
import { PROMPT_SYNTAX_CLASS, promptSyntaxSpans } from '../utils/promptSyntax.ts'
import type { ViewPromptPiece } from './types.ts'

const props = withDefaults(defineProps<{
  /** The prompt the image was made from. */
  prompt: string | null | undefined
  /** The prompt as the user typed it, when it differs. */
  typed?: string | null
  /** The prompt with its slots and lists filled in, before it was improved. */
  filled?: ViewPromptPiece[] | null
  /** How much the improver added ("High detail"). */
  detail?: string | null
  improved?: boolean
  label?: string
}>(), {
  typed: null,
  filled: null,
  detail: null,
  improved: false,
  label: '',
})

interface Piece { text: string; cls?: string; title?: string; syntax?: string }
interface Stage { key: string; label: string; note?: string; text: string; pieces: Piece[]; final: boolean }

const host = useProvenanceHost()
const same = (a: string, b: string) => a.trim() === b.trim()

function typedPieces(text: string): Piece[] {
  return promptSyntaxSpans(text).map(span => span.kind
    ? { text: span.text, cls: PROMPT_SYNTAX_CLASS[span.kind], syntax: span.kind }
    : { text: span.text })
}

function filledPieces(pieces: ViewPromptPiece[]): Piece[] {
  return pieces.map(piece => {
    if (!piece.kind) return { text: piece.text }
    const syntax = piece.kind === 'list' ? 'wildcard' : 'slot'
    const title = piece.from ? (piece.kind === 'slot' ? `<${piece.from}>` : piece.from) : undefined
    return { text: piece.text, cls: PROMPT_SYNTAX_CLASS[syntax], title, syntax }
  })
}

const stages = computed<Stage[]>(() => {
  const final = props.prompt || props.typed || ''
  if (!final.trim()) return []
  const typed = props.prompt && props.typed && !same(props.typed, final) ? props.typed : null
  const filled = props.filled?.length ? props.filled : null
  const filledText = filled ? filled.map(p => p.text).join('') : ''
  const filledIsFinal = !!filled && same(filledText, final)

  const out: Stage[] = []
  if (typed) out.push({ key: 'typed', label: 'You wrote', text: typed, pieces: typedPieces(typed), final: false })
  if (filled && !filledIsFinal && !(typed && same(filledText, typed))) {
    out.push({ key: 'filled', label: 'Filled in', text: filledText, pieces: filledPieces(filled), final: false })
  }
  if (filledIsFinal && filled) {
    out.push({ key: 'final', label: 'Filled in', text: final, pieces: filledPieces(filled), final: true })
  } else if (props.improved || filled) {
    out.push({ key: 'final', label: 'Improved', note: props.detail || undefined, text: final, pieces: [{ text: final }], final: true })
  } else {
    out.push({ key: 'final', label: 'Sent', text: final, pieces: [{ text: final }], final: true })
  }
  return out
})
const last = computed(() => stages.value[stages.value.length - 1] ?? null)

// Each item opens with its earlier stages closed; the choice doesn't carry over.
const open = ref<Set<string>>(new Set())
watch(() => [props.prompt, props.typed, props.filled], () => { open.value = new Set() })
const isOpen = (key: string) => open.value.has(key)
function toggle(key: string) {
  const next = new Set(open.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  open.value = next
}

function copy(text: string) {
  if (text && host.copy) void host.copy(text)
}

function copyOnClick(text: string) {
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return
  copy(text)
}
</script>
