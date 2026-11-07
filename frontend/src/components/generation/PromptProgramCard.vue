<template>
  <!-- A choice's card. Each image draws one of the options; ticking some limits the
       draw to those. The model can write more options or a whole new set. -->
  <Teleport to="body">
    <div v-if="card" class="fixed inset-0 z-menu" @click="program.close()">
      <div
        ref="menuRef"
        data-escape-layer
        data-program-card
        :class="['fixed z-menu bg-surface border border-edge-subtle rounded-lg shadow-lg max-w-[calc(100vw-16px)] flex flex-col max-h-[70vh]', wide ? 'w-[420px]' : 'w-[340px]']"
        :style="menuStyle"
        @click.stop
      >
        <!-- One person's attribute, opened from the group grid -->
        <template v-if="member">
          <CardHeader :title="`${group?.label} ${member.index} · ${member.label}`" :back="group?.label" :choice="member" :program="program" @back="memberId = null" />
          <OptionRows :choice="member" :program="program" deletable addable />
        </template>

        <!-- A group (People ×3): rows are attributes, columns are people -->
        <template v-else-if="group">
          <CardHeader :title="`${group.label} ×${group.count}`" />
          <div class="px-3 pb-3 overflow-y-auto">
            <table class="w-full border-collapse">
              <tr>
                <th />
                <th v-for="i in group.count" :key="i" class="text-[11px] font-medium text-content-tertiary text-left px-1 pb-1">{{ i }}</th>
              </tr>
              <tr v-for="attr in groupAttrs" :key="attr">
                <td class="pr-2 py-0.5 text-xs text-content-secondary whitespace-nowrap align-middle">
                  <WandSparklesIcon v-if="attrChoice(attr, 1)?.source === 'added'" class="inline w-2.5 h-2.5 mr-0.5 text-content-tertiary" />{{ attrChoice(attr, 1)?.label }}
                </td>
                <td v-for="i in group.count" :key="i" class="px-0.5 py-0.5">
                  <button
                    v-if="attrChoice(attr, i)"
                    type="button"
                    :class="['w-full text-left px-2 py-1 text-xs rounded-md truncate max-w-[9rem] outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
                      program.isPinned(attrChoice(attr, i)!) ? 'bg-selection/15 text-selection' : 'bg-overlay-subtle text-content-secondary hover:text-content']"
                    @click="memberId = attrChoice(attr, i)!.id"
                  >{{ program.valueText(attrChoice(attr, i)!) }}</button>
                </td>
              </tr>
            </table>
            <button v-if="groupLimited" type="button" class="mt-2 text-xs text-content-tertiary hover:text-content" @click="clearGroup">Use all options for everyone</button>
          </div>
        </template>

        <!-- One choice -->
        <template v-else-if="choice">
          <CardHeader
            :title="choice.label"
            :note="note"
            :added="choice.source === 'added'"
            :choice="choice.kind === 'param' ? undefined : choice"
            :program="program"
          />
          <div v-if="choice.kind === 'param'" class="px-3 pb-3 text-xs text-content-secondary">
            Each image draws a value from <span class="font-mono text-selection">{{ choice.options[0] }} – {{ choice.options[1] }}</span>.
          </div>
          <template v-else>
            <OptionRows
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
                <button type="button" :class="footClass" :disabled="!!writing" title="Replace every option with a new set" @click="write('reroll')">
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
import { computed, defineComponent, h, nextTick, ref, watch } from 'vue'
import { ArrowPathIcon, CheckIcon, ChevronLeftIcon, PlusIcon, SparklesIcon, TrashIcon } from '@heroicons/vue/24/outline'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import { PROMPT_BRAND } from './promptBrand'
import Spinner from '../ui/Spinner.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()

const footClass = 'flex items-center gap-1.5 px-2 py-1 coarse:py-2 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle disabled:opacity-50 disabled:pointer-events-none'

const card = computed(() => props.program.openCard.value)
const menuRef = ref<HTMLElement | null>(null)
const anchorRect = computed(() => card.value?.anchor ?? null)
const visible = computed(() => !!card.value)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const memberId = ref<string | null>(null)
watch(() => card.value?.id, () => { memberId.value = null; writeError.value = '' })

const choice = computed(() => {
  const id = card.value?.id
  return id && !id.startsWith('group:') ? props.program.byId.value[id] : null
})
const group = computed(() => {
  const id = card.value?.id
  if (!id?.startsWith('group:')) return null
  const gid = id.slice(6)
  return props.program.program.value?.groups.find(g => g.id === gid) || null
})
const members = computed(() => group.value ? props.program.choices.value.filter(c => c.group === group.value!.id) : [])
const groupAttrs = computed(() => [...new Set(members.value.map(m => m.attr || m.id))])
const member = computed(() => memberId.value ? props.program.byId.value[memberId.value] : null)
const groupLimited = computed(() => members.value.some(m => props.program.isPinned(m)))
// Phrase-length options get a wider card so they wrap less.
const wide = computed(() => {
  const c = member.value || choice.value
  return !!c && props.program.optionsOf(c).some(o => o.length > 32)
})

// The user's own {a|b} list and LoRA choices keep exactly what the user gave.
const editable = computed(() => !!choice.value && choice.value.source !== 'list' && choice.value.kind === 'pick')
// The model writes options for plain picks (not ones whose options depend on another pick).
const writable = computed(() => editable.value && !choice.value!.follows)

function attrChoice(attr: string, index: number): ProgramChoice | undefined {
  return members.value.find(m => (m.attr || m.id) === attr && m.index === index)
}

const note = computed(() => {
  const c = choice.value
  if (!c) return ''
  const parts: string[] = []
  if (c.source === 'added') parts.push(`Added by ${PROMPT_BRAND}`)
  if (c.kind === 'lora') parts.push('each turns on its LoRA')
  if (c.parent) {
    const p = props.program.byId.value[c.parent]
    parts.push(`only when ${p?.label || c.parent} is ${(c.when || []).join(' or ')}`)
  }
  if (c.follows) parts.push(`follows ${props.program.byId.value[c.follows]?.label || c.follows}`)
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
function clearGroup() {
  const next: Record<string, string[]> = {}
  for (const m of members.value) next[m.id] = []
  props.program.setManyPins(next)
}

// Header: the choice's name, and "Use all" once some options are ticked -------------
const CardHeader = defineComponent({
  props: { title: String, note: String, back: String, added: Boolean, choice: Object, program: Object },
  emits: ['back'],
  setup(p, { emit: e }) {
    return () => {
      const prog = p.program as PromptProgram | undefined
      const c = p.choice as ProgramChoice | undefined
      const limited = !!(prog && c && (prog.pins.value[c.id] || []).some(v => prog.optionsOf(c).includes(v)))
      return h('div', { class: 'px-3 pt-2.5 pb-1.5 flex items-start gap-2' }, [
        p.back ? h('button', {
          type: 'button', class: 'mt-0.5 -ml-1 p-0.5 rounded text-content-tertiary hover:text-content', title: `Back to ${p.back}`,
          onClick: () => e('back'),
        }, [h(ChevronLeftIcon, { class: 'w-3.5 h-3.5' })]) : null,
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

// Option rows: tick to limit the draw, trash to delete, and a field to add your own ----
const OptionRows = defineComponent({
  props: { choice: { type: Object, required: true }, program: { type: Object, required: true }, deletable: Boolean, addable: Boolean },
  setup(p) {
    const draft = ref('')
    const list = ref<HTMLElement | null>(null)
    return () => {
      const prog = p.program as PromptProgram
      const c = p.choice as ProgramChoice
      const opts = prog.optionsOf(c)
      const pinned = new Set(prog.pins.value[c.id] || [])
      const edit = prog.edits.value[c.id] || {}
      const lora = (name: string) => prog.program.value?.loras.find(l => l.name === name)
      const toggle = (o: string) => {
        const next = new Set(pinned)
        next.has(o) ? next.delete(o) : next.add(o)
        prog.setPins(c.id, opts.filter(x => next.has(x)))
      }
      const del = (o: string) => {
        const added = (edit.add || []).filter(x => x !== o)
        const removed = c.options.includes(o) ? [...new Set([...(edit.remove || []), o])] : edit.remove
        prog.setEdit(c.id, { ...edit, add: added, remove: removed })
        prog.setPins(c.id, [...pinned].filter(x => x !== o))
      }
      const commit = () => {
        const v = draft.value.trim()
        if (v && !opts.includes(v)) {
          prog.setEdit(c.id, { ...edit, add: [...(edit.add || []), v] })
          void nextTick(() => list.value?.scrollTo({ top: list.value.scrollHeight }))
        }
        draft.value = ''
      }
      const rows = opts.map(o => {
        const on = pinned.has(o)
        return h('div', {
          key: o,
          role: 'checkbox', 'aria-checked': on, tabindex: 0,
          class: ['group/opt flex items-start gap-2.5 px-2 py-1.5 coarse:py-2.5 rounded-md cursor-pointer outline-none focus-visible:ring-1 focus-visible:ring-selection/60',
            on ? 'bg-selection/10' : 'hover:bg-overlay-subtle'],
          onClick: () => toggle(o),
          onKeydown: (e: KeyboardEvent) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(o) } },
        }, [
          h('span', {
            class: ['mt-[2px] shrink-0 w-3.5 h-3.5 rounded-[4px] flex items-center justify-center border',
              on ? 'bg-selection border-selection text-white' : 'border-edge-strong'],
          }, on ? [h(CheckIcon, { class: 'w-2.5 h-2.5', 'stroke-width': 3 })] : []),
          h('span', { class: ['flex-1 min-w-0 text-xs coarse:text-[13px] leading-snug break-words', on ? 'text-content' : 'text-content-secondary group-hover/opt:text-content'] }, [
            o,
            lora(o)?.trigger ? h('span', { class: 'ml-1.5 font-mono text-[10px] text-content-muted' }, lora(o)!.trigger.split(',')[0]) : null,
          ]),
          p.deletable ? h('button', {
            type: 'button', title: 'Delete option', 'aria-label': `Delete ${o}`,
            class: 'shrink-0 -my-0.5 p-0.5 rounded text-content-muted hover:text-red-400 opacity-0 group-hover/opt:opacity-100 focus-visible:opacity-100 coarse:opacity-100',
            onClick: (e: Event) => { e.stopPropagation(); del(o) },
          }, [h(TrashIcon, { class: 'w-3.5 h-3.5' })]) : null,
        ])
      })
      return h('div', { class: 'min-h-0 flex flex-col' }, [
        h('div', { ref: list, class: 'min-h-0 overflow-y-auto px-1.5 pb-1.5 flex flex-col gap-px' }, rows),
        p.addable ? h('div', { class: 'px-1.5 pb-1.5' }, [
          h('div', { class: 'flex items-center gap-2.5 px-2 py-1 rounded-md focus-within:bg-overlay-subtle' }, [
            h(PlusIcon, { class: 'shrink-0 w-3.5 h-3.5 text-content-muted' }),
            h('input', {
              class: 'flex-1 min-w-0 bg-transparent text-xs coarse:text-[13px] text-content placeholder:text-content-muted outline-none py-0.5',
              placeholder: 'Add your own…', value: draft.value,
              onInput: (e: Event) => { draft.value = (e.target as HTMLInputElement).value },
              onKeydown: (e: KeyboardEvent) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape' && draft.value) { draft.value = ''; e.stopPropagation() }
              },
              onBlur: commit,
            }),
          ]),
        ]) : null,
      ])
    }
  },
})
</script>
