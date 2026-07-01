<template>
  <div v-if="skills.length > 0">
    <button
      ref="buttonRef"
      @click="toggle"
      class="relative w-8 h-8 flex items-center justify-center rounded-full transition-colors"
      :class="activeCount > 0
        ? 'text-blue-400 hover:bg-blue-500/10'
        : 'text-content-muted hover:text-content-secondary hover:bg-white/[0.05]'"
      :title="title"
    >
      <BookOpenIcon class="w-5 h-5" />
      <span
        v-if="activeCount > 0"
        class="absolute -top-0.5 -right-0.5 min-w-[14px] h-3.5 px-1 rounded-full bg-blue-500 text-white text-[9px] font-medium flex items-center justify-center"
      >{{ activeCount }}</span>
    </button>

    <!-- Teleported so the menu escapes ancestor stacking contexts and
         overflow clipping (the input box lives inside overflow-hidden
         containers on several surfaces). -->
    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-[10040]" @click="open = false"></div>
      <div
        v-if="open"
        class="fixed w-80 z-[10050] bg-surface border border-edge rounded-xl shadow-2xl overflow-hidden"
        :style="menuPosition"
      >
        <div class="px-3 pt-2.5 pb-1.5">
          <span class="text-xs font-medium text-content-tertiary">{{ mode === 'view' ? 'Active skills' : 'Skills' }}</span>
          <p class="text-[11px] text-content-muted mt-0.5">
            {{ mode === 'view'
              ? 'These skills match this tool and guide the assistant automatically.'
              : 'Activated skills guide the agent for the rest of the conversation.' }}
          </p>
        </div>
        <div class="max-h-64 overflow-y-auto">
          <div
            v-for="(skill, idx) in skills"
            :key="skill.qualified_name"
            class="flex items-center justify-between px-3 py-2"
            :class="idx < skills.length - 1 ? 'border-b border-edge' : ''"
          >
            <div class="min-w-0 mr-2">
              <div class="flex items-center gap-2">
                <span
                  class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  :class="isActive(skill) ? 'bg-blue-500' : 'bg-white/10'"
                />
                <span
                  class="text-xs leading-4"
                  :class="isActive(skill) ? 'text-content font-medium' : 'text-content-secondary'"
                >{{ skill.display_name || skill.slug }}</span>
              </div>
              <p v-if="skill.description" class="text-[10px] text-content-muted truncate mt-0.5 pl-3.5">{{ skill.description }}</p>
            </div>
            <div v-if="mode === 'activate'" class="flex items-center flex-shrink-0">
              <button
                v-if="!isActive(skill)"
                @click="$emit('activate', skill.qualified_name)"
                :disabled="invoking === skill.qualified_name"
                class="text-[10px] px-2 py-0.5 rounded text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 transition-colors disabled:opacity-50"
              >
                {{ invoking === skill.qualified_name ? 'Activating...' : 'Activate' }}
              </button>
              <span v-else class="text-[10px] text-content-muted px-2">Active</span>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { BookOpenIcon } from '@heroicons/vue/24/outline'

interface SkillEntry {
  qualified_name: string
  display_name: string
  slug?: string
  pack_name?: string
  description?: string
}

const props = withDefaults(defineProps<{
  /** Skills eligible on this surface. The button hides itself when empty. */
  skills: SkillEntry[]
  /**
   * Names counting as active — qualified names, plus legacy bare slugs and
   * pack names from old history. In 'view' mode every listed skill is active.
   */
  activeKeys?: Set<string> | string[]
  /** 'activate' shows per-skill Activate buttons; 'view' is status-only. */
  mode?: 'activate' | 'view'
  /** Qualified name of the skill currently being activated, if any. */
  invoking?: string | null
}>(), {
  activeKeys: () => [],
  mode: 'activate',
  invoking: null,
})

defineEmits<{ (e: 'activate', qualifiedName: string): void }>()

const open = ref(false)
const buttonRef = ref<HTMLElement | null>(null)
const menuPosition = ref<Record<string, string>>({})

const MENU_WIDTH = 320 // w-80

function toggle() {
  if (!open.value && buttonRef.value) {
    const rect = buttonRef.value.getBoundingClientRect()
    // Open upward from the button, left-aligned, clamped to the viewport.
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - MENU_WIDTH - 8))
    menuPosition.value = {
      left: `${left}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
    }
  }
  open.value = !open.value
}

const keySet = computed(() =>
  props.activeKeys instanceof Set ? props.activeKeys : new Set(props.activeKeys)
)

function isActive(skill: SkillEntry): boolean {
  if (props.mode === 'view') return true
  return keySet.value.has(skill.qualified_name)
    || (!!skill.slug && keySet.value.has(skill.slug))
    || (!!skill.pack_name && keySet.value.has(skill.pack_name))
}

const activeCount = computed(() =>
  props.mode === 'view' ? props.skills.length : props.skills.filter(isActive).length
)

const title = computed(() => {
  if (activeCount.value > 0) {
    const names = props.skills.filter(isActive).map(s => s.display_name).join(', ')
    return `Active skills: ${names}`
  }
  return 'Skills'
})
</script>
