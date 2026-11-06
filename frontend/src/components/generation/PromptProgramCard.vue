<template>
  <!-- A choice's card: the same look as the prompt-idea submenu. Options are pills;
       selecting some limits the draw, one pins it, none is "any". -->
  <Teleport to="body">
    <div v-if="card" class="fixed inset-0 z-menu" @click="program.close()" @keydown.escape="program.close()">
      <div
        ref="menuRef"
        data-escape-layer
        data-program-card
        :class="['fixed z-menu suggestion-submenu-card rounded-lg border border-edge p-3 max-w-[calc(100vw-16px)]', long ? 'w-[420px]' : 'w-[340px]']"
        :style="menuStyle"
        @click.stop
      >
        <!-- One person's attribute, opened from the group grid -->
        <template v-if="member">
          <div class="relative text-xs font-semibold text-content-secondary text-center mb-0.5">
            <button type="button" class="absolute left-0 top-0 font-medium text-content-tertiary hover:text-content-secondary" @click="memberId = null">‹ {{ group?.label }}</button>
            {{ group?.label }} {{ member.index }} · {{ attrLabel(member) }}
          </div>
          <div v-if="ruleNote(member)" class="text-[11px] text-content-muted text-center mb-2">{{ ruleNote(member) }}</div>
          <OptionPills :choice="member" :program="program" deletable />
          <div class="border-t border-edge mt-2 pt-2 flex justify-center gap-1">
            <button type="button" :class="actionClass" @click="program.setPins(member.id, [])">any</button>
          </div>
        </template>

        <!-- A group (People ×3): rows are attributes, columns are people -->
        <template v-else-if="group">
          <div class="text-xs font-semibold text-content-secondary text-center">{{ group.label }} ×{{ group.count }}</div>
          <div class="text-[11px] text-content-muted text-center mb-2">From your prompt</div>
          <table class="w-full border-collapse">
            <tr>
              <th />
              <th v-for="i in group.count" :key="i" class="text-[11px] font-semibold text-content-tertiary text-left px-1 pb-1">{{ i }}</th>
            </tr>
            <tr v-for="attr in groupAttrs" :key="attr">
              <td class="pr-2 py-0.5 text-[12px] text-content-secondary whitespace-nowrap align-middle">
                <WandSparklesIcon v-if="attrChoice(attr, 1)?.source === 'added'" class="inline w-2.5 h-2.5 mr-0.5 text-content-tertiary" />{{ attrLabel(attrChoice(attr, 1)) }}
              </td>
              <td v-for="i in group.count" :key="i" class="px-1 py-0.5">
                <button
                  v-if="attrChoice(attr, i)"
                  type="button"
                  :class="['px-2 py-0.5 text-[11.5px] rounded-full whitespace-nowrap suggestion-submenu-pill', program.isPinned(attrChoice(attr, i)!) ? '!bg-selection/20 !text-selection' : '']"
                  @click="memberId = attrChoice(attr, i)!.id"
                >{{ program.valueText(attrChoice(attr, i)!) }}</button>
              </td>
            </tr>
          </table>
          <div class="border-t border-edge mt-2 pt-2 flex justify-center gap-1">
            <button type="button" :class="actionClass" @click="clearGroup">any</button>
            <button v-if="group.line" type="button" :class="actionClass" @click="show(group.line)">show in prompt</button>
          </div>
        </template>

        <!-- One choice -->
        <template v-else-if="choice">
          <div class="flex items-center justify-center gap-1 text-xs font-semibold text-content-secondary text-center">
            <WandSparklesIcon v-if="choice.source === 'added'" class="w-3 h-3 text-content-tertiary" />
            {{ choice.label }}
          </div>
          <div class="text-[11px] text-content-muted text-center mb-2 break-words">{{ note }}</div>
          <div v-if="choice.kind === 'param'" class="flex flex-col items-center gap-0.5 py-1">
            <span class="font-mono text-[13px] text-selection">{{ choice.options[0] }} – {{ choice.options[1] }}</span>
            <span class="text-[11px] text-content-muted">each image draws a value</span>
          </div>
          <OptionPills v-else :choice="choice" :program="program" :long="long" :deletable="choice.source !== 'list' && choice.kind !== 'lora'" :addable="choice.source !== 'list' && choice.kind !== 'lora'" />
          <div class="border-t border-edge mt-2 pt-2 flex justify-center gap-1">
            <button v-if="choice.kind !== 'param'" type="button" :class="actionClass" @click="program.setPins(choice.id, [])">any</button>
            <button v-if="choice.line && choice.source !== 'added'" type="button" :class="actionClass" @click="show(choice.line)">show in prompt</button>
            <button v-if="choice.source === 'added'" type="button" :class="[actionClass, 'hover:!text-red-400']" @click="removeChoice">remove</button>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref, watch } from 'vue'
import WandSparklesIcon from '../icons/WandSparklesIcon.vue'
import { useAnchoredMenuPosition } from '../../composables/useContextMenuPosition'
import type { PromptProgram, ProgramChoice } from '../../composables/usePromptProgram'

const props = defineProps<{ program: PromptProgram }>()
const emit = defineEmits<{ (e: 'show-line', line: number): void }>()

const actionClass = 'flex items-center gap-1 px-2 py-1 text-xs rounded-full whitespace-nowrap text-content-muted hover:text-content-secondary suggestion-submenu-pill'

const card = computed(() => props.program.openCard.value)
const menuRef = ref<HTMLElement | null>(null)
const anchorRect = computed(() => card.value?.anchor ?? null)
const visible = computed(() => !!card.value)
const { menuStyle } = useAnchoredMenuPosition(menuRef, anchorRect, visible, { gap: 6 })

const memberId = ref<string | null>(null)
watch(() => card.value?.id, () => { memberId.value = null })

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
// Phrase-length options read as a list of wrapped rows, not pills that scroll sideways.
const long = computed(() => !!choice.value && props.program.optionsOf(choice.value).some(o => o.length > 32))

function attrChoice(attr: string, index: number): ProgramChoice | undefined {
  return members.value.find(m => (m.attr || m.id) === attr && m.index === index)
}
function attrLabel(c?: ProgramChoice) {
  return c?.label || ''
}
function ruleNote(_c: ProgramChoice) {
  return ''
}

const note = computed(() => {
  const c = choice.value
  if (!c) return ''
  const parts: string[] = []
  parts.push(c.wildcard ? `From your {{${c.wildcard}}}` : c.source === 'list' ? 'From your {…} list' : c.source === 'added' ? 'Added by Enhance' : 'From your prompt')
  if (c.kind === 'lora') parts.push('each turns on its LoRA')
  if (c.parent) {
    const p = props.program.byId.value[c.parent]
    parts.push(`only when ${p?.label || c.parent} is ${(c.when || []).join(' or ')}`)
  }
  if (c.follows) parts.push(`follows ${props.program.byId.value[c.follows]?.label || c.follows}`)
  return parts.join(' · ')
})

function show(line: number) {
  props.program.close()
  emit('show-line', line)
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

// Option pills (with delete and add) -----------------------------------------------
const OptionPills = defineComponent({
  props: { choice: { type: Object, required: true }, program: { type: Object, required: true }, deletable: Boolean, addable: Boolean, long: Boolean },
  setup(p) {
    const adding = ref(false)
    const draft = ref('')
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
        if (v && !opts.includes(v)) prog.setEdit(c.id, { ...edit, add: [...(edit.add || []), v] })
        draft.value = ''
        adding.value = false
      }
      const pills = opts.map(o => h('button', {
        type: 'button', key: o,
        class: ['group/opt relative text-xs transition-all duration-150 suggestion-submenu-pill coarse:text-[13px]',
          p.long ? 'px-3 py-1.5 rounded-lg text-left leading-snug' : 'px-2.5 py-1 rounded-full whitespace-nowrap coarse:py-1.5',
          pinned.has(o) ? '!bg-selection/20 !text-selection' : ''],
        onClick: () => toggle(o),
      }, [
        o,
        lora(o)?.trigger ? h('span', { class: 'ml-1 font-mono text-[10px] opacity-60' }, lora(o)!.trigger.split(',')[0]) : null,
        p.deletable ? h('span', {
          class: 'hidden group-hover/opt:flex absolute -top-1.5 -right-1.5 w-4 h-4 items-center justify-center rounded-full bg-surface-active text-content text-[10px] coarse:flex',
          title: 'Delete option',
          onClick: (e: Event) => { e.stopPropagation(); del(o) },
        }, '×') : null,
      ]))
      if (p.addable) {
        pills.push(adding.value
          ? h('input', {
              class: 'px-2.5 py-1 text-xs rounded-full bg-transparent border border-dashed border-edge-strong text-content outline-none w-32',
              placeholder: 'new option', value: draft.value, autofocus: true,
              onInput: (e: Event) => { draft.value = (e.target as HTMLInputElement).value },
              onKeydown: (e: KeyboardEvent) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { adding.value = false; e.stopPropagation() } },
              onBlur: commit,
            })
          : h('button', {
              type: 'button',
              class: 'px-2.5 py-1 text-xs rounded-full border border-dashed border-edge-strong text-content-tertiary hover:text-content-secondary',
              onClick: () => { adding.value = true },
            }, '+ add'))
      }
      return h('div', { class: ['max-h-[50vh] overflow-y-auto overflow-x-hidden p-1.5 -m-1', p.long ? 'flex flex-col gap-1' : 'flex flex-wrap justify-center gap-1.5'] }, pills)
    }
  },
})
</script>
