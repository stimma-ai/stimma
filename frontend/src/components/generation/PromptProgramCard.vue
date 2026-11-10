<template>
  <!-- A choice's card. Each image draws one of the options; ticking some limits the
       draw to those. The model can write more options or a whole new set. -->
  <Teleport to="body">
    <div v-if="card" class="fixed inset-0 z-menu" @click="program.close()">
      <div
        ref="menuRef"
        data-escape-layer
        data-program-card
        role="dialog"
        :aria-label="choiceTitle || undefined"
        :class="['fixed z-menu bg-surface border border-edge-subtle rounded-lg shadow-lg max-w-[calc(100vw-16px)] flex flex-col max-h-[70vh]', wide ? 'w-[420px]' : 'w-[340px]']"
        :style="menuStyle"
        @click.stop
      >
        <template v-if="choice">
          <CardHeader
            :title="choiceTitle"
            :note="note"
            :added="choice.source === 'added'"
            :choice="choice.kind === 'param' ? undefined : choice"
            :program="program"
          />
          <div v-if="choice.kind === 'param'" class="px-3 pb-3 text-xs text-content-secondary">
            Each image draws a value from <span class="font-mono text-selection">{{ choice.options[0] }} – {{ choice.options[1] }}</span>.
          </div>
          <template v-else>
            <PromptProgramOptions
              :choice="choice"
              :program="program"
              :deletable="editable"
              :addable="editable"
            />
            <div v-if="writable || choice.source === 'added'" class="border-t border-edge-subtle px-2 py-1.5 flex items-center gap-1">
              <template v-if="writable">
                <button type="button" :class="footClass" :disabled="!!writing" @click="write('more')">
                  <Spinner v-if="writing === 'more'" size="sm" /><SparklesIcon v-else class="w-3.5 h-3.5" />
                  More like these
                </button>
                <button v-if="!bound" type="button" :class="footClass" :disabled="!!writing" title="Replace every option with a new set" @click="write('reroll')">
                  <Spinner v-if="writing === 'reroll'" size="sm" /><ArrowPathIcon v-else class="w-3.5 h-3.5" />
                  New set
                </button>
              </template>
              <span class="flex-1" />
              <button v-if="choice.source === 'added'" type="button" :class="[footClass, 'hover:!text-red-400']" title="Stop varying this; the image model decides it" @click="removeChoice">
                <TrashIcon class="w-3.5 h-3.5" /> Remove
              </button>
            </div>
            <div v-if="writeError" class="px-3 pb-2 text-[11px] text-red-400">{{ writeError }}</div>
          </template>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onUnmounted, ref, watch } from 'vue'
import { ArrowPathIcon, SparklesIcon, TrashIcon } from '@heroicons/vue/24/outline'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import { programLabel, programSections } from '../../utils/programChoiceLayout'
import { PROMPT_BRAND } from './promptBrand'
import Spinner from '../ui/Spinner.vue'
import PromptProgramOptions from './PromptProgramOptions.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none'

const card = computed(() => props.program.openCard.value)
const menuRef = ref<HTMLElement | null>(null)
const anchorRect = computed(() => card.value?.anchor ?? null)
const visible = computed(() => !!card.value)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

watch(() => card.value?.id, () => { writeError.value = '' })

// Keyboard: the card is teleported to the end of the page, so focus moves into it when
// it opens, Tab stays inside, Escape closes it, and focus goes back to what opened it.
// Escape listens on the window in the bubble phase, so a search or draft that clears
// itself on Escape (and stops it) keeps that one.
let returnTo: HTMLElement | null = null
function focusables(): HTMLElement[] {
  return [...(menuRef.value?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])]
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    props.program.close()
  } else if (e.key === 'Tab') {
    const all = focusables()
    if (!all.length) return
    const i = all.indexOf(document.activeElement as HTMLElement)
    const next = e.shiftKey ? (i <= 0 ? all.length - 1 : i - 1) : (i === -1 || i === all.length - 1 ? 0 : i + 1)
    all[next].focus()
    e.preventDefault()
  }
}
watch(visible, (open) => {
  if (open) {
    returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    window.addEventListener('keydown', onKey)
    void nextTick(() => { if (!menuRef.value?.contains(document.activeElement)) focusables()[0]?.focus() })
  } else {
    window.removeEventListener('keydown', onKey)
    const back = returnTo
    returnTo = null
    if (back?.isConnected) back.focus()
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKey))

const choice = computed(() => {
  const id = card.value?.id
  return id ? props.program.byId.value[id] : null
})
const choiceTitle = computed(() => {
  const c = choice.value
  if (!c) return ''
  const section = programSections(props.program.choices.value, props.program.program.value?.groups || [])
    .find(s => s.label && s.choices.some(member => member.id === c.id))
  return [section?.label, programLabel(c.label)].filter(Boolean).join(' · ')
})
// Phrase-length options get a wider card so they wrap less.
const wide = computed(() => {
  const c = choice.value
  return !!c && props.program.optionsOf(c).some(o => o.length > 32)
})

// The user's own {a|b} list and LoRA choices keep exactly what the user gave.
const editable = computed(() => !!choice.value && choice.value.source !== 'list' && choice.value.kind === 'pick')
// Drawn from a vocabulary list: its values are the options.
const bound = computed(() => !!choice.value && (!!choice.value.cls || !!props.program.vocabOf(choice.value)))
// The model writes options for plain picks (not ones whose options depend on another
// pick), and adds to an open list; a closed list is complete as it is. A whole new set
// would throw the list away, so list-drawn picks only get More like these.
const writable = computed(() => editable.value && !choice.value!.follows && !props.program.vocabOf(choice.value!)?.closed)
const note = computed(() => {
  const c = choice.value
  if (!c) return ''
  const parts: string[] = []
  if (c.source === 'added') parts.push(`Added by ${PROMPT_BRAND}`)
  if (c.kind === 'lora') parts.push('each turns on its LoRA')
  if (c.parent) {
    const p = props.program.byId.value[c.parent]
    parts.push(`only when ${programLabel(p?.label || c.parent)} is ${(c.when || []).join(' or ')}`)
  }
  if (c.follows) parts.push(`follows ${programLabel(props.program.byId.value[c.follows]?.label || c.follows)}`)
  return parts.join(' · ')
})

const writing = ref<'' | 'more' | 'reroll'>('')
const writeError = ref('')
async function write(mode: 'more' | 'reroll') {
  const c = choice.value
  if (!c || writing.value) return
  writing.value = mode
  writeError.value = ''
  try {
    // New set replaces the options with as many new ones; More adds six.
    await props.program.suggestOptions(c, mode, mode === 'reroll' ? props.program.optionsOf(c).length : 6)
  } catch (e: any) {
    const d = e?.response?.data?.detail
    writeError.value = (typeof d === 'string' ? d : d?.message) || 'Couldn’t write new options.'
  } finally {
    writing.value = ''
  }
}

function removeChoice() {
  const c = choice.value
  if (!c) return
  props.program.setEdit(c.id, { ...(props.program.edits.value[c.id] || {}), off: true })
  props.program.setPins(c.id, [])
  props.program.close()
}
// Header: the choice's name, and "Use all" once some options are ticked -------------
const CardHeader = defineComponent({
  props: { title: String, note: String, added: Boolean, choice: Object, program: Object },
  setup(p) {
    return () => {
      const prog = p.program as PromptProgram | undefined
      const c = p.choice as ProgramChoice | undefined
      const limited = !!(prog && c && (prog.pins.value[c.id] || []).some(v => prog.optionsOf(c).includes(v)))
      return h('div', { class: 'px-3 pt-2.5 pb-1.5 flex items-start gap-2' }, [
        h('div', { class: 'min-w-0 flex-1' }, [
          h('div', { class: 'flex items-center gap-1 text-[13px] font-semibold text-content' }, [
            p.added ? h(WandSparklesIcon, { class: 'w-3 h-3 text-content-tertiary' }) : null, p.title,
          ]),
          p.note ? h('div', { class: 'text-[11px] text-content-muted break-words leading-snug' }, p.note) : null,
        ]),
        limited ? h('button', {
          type: 'button', class: 'shrink-0 mt-0.5 text-[11px] text-content-tertiary hover:text-content',
          title: 'Draw from every option again', onClick: () => prog!.setPins(c!.id, []),
        }, 'Use all') : null,
      ])
    }
  },
})
</script>
