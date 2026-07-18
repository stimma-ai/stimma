<template>
  <Teleport to="body">
    <Transition name="menu">
      <div
        v-if="visible"
        ref="menuRef"
        class="fixed z-menu min-w-[200px] bg-surface border border-edge-subtle rounded-lg shadow-lg py-1"
        :style="menuStyle"
        @click.stop
      >
        <template v-for="(action, index) in actions" :key="index">
          <div v-if="action.divider || action.id === 'divider'" class="h-px my-1 mx-2 bg-edge-subtle" />
          <div
            v-else
            class="flex items-center gap-2 px-3 py-2 text-xs select-none cursor-pointer transition-colors"
            :class="action.disabled
              ? 'opacity-50 cursor-not-allowed text-content-secondary'
              : action.danger
                ? 'text-red-400 hover:bg-overlay-subtle'
                : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
            @click="handleAction(action)"
          >
            <span v-if="action.icon" class="w-[18px] h-[18px] flex items-center justify-center flex-shrink-0 [&_svg]:w-full [&_svg]:h-full [&_svg]:text-current" v-html="sanitizeSvg(action.icon)" />
            <span class="flex-1">{{ action.label }}</span>
            <span v-if="action.shortcut" class="ml-auto text-[11px] text-content-muted">{{ action.shortcut }}</span>
          </div>
        </template>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { useContextMenuPosition } from '../composables/useContextMenuPosition'

const props = defineProps({
  visible: {
    type: Boolean,
    default: true  // Default to true so v-if on parent works
  },
  position: {
    type: Object,
    default: null
  },
  // Alternative to position object - pass x and y separately
  x: {
    type: Number,
    default: null
  },
  y: {
    type: Number,
    default: null
  },
  actions: {
    type: Array,
    default: () => []
    // Expected format: [{ id, label, icon?, disabled?, danger?, action?: () => {}, shortcut?, divider? }]
  }
})

const emit = defineEmits(['close', 'select'])

// Computed position - use position object if provided, otherwise use x/y props
const computedPosition = computed(() => {
  if (props.position) {
    return props.position
  }
  return { x: props.x ?? 0, y: props.y ?? 0 }
})

const menuRef = ref(null)

// Viewport-aware positioning (clamps to window, re-clamps as content resizes)
const menuCoords = computed(() => computedPosition.value)
const menuVisible = computed(() => props.visible)
const { menuStyle } = useContextMenuPosition(menuRef, menuCoords, menuVisible)

function handleAction(action) {
  if (action.disabled || action.divider || action.id === 'divider') return

  // If action has its own handler, call it
  if (action.action) {
    action.action()
  }

  // Emit select event with action id for parent handling
  emit('select', action.id)
  emit('close')
}

function handleClickOutside(event) {
  if (props.visible && menuRef.value && !menuRef.value.contains(event.target)) {
    emit('close')
  }
}

function handleEscape(event) {
  if (event.key === 'Escape' && props.visible) {
    emit('close')
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('contextmenu', handleClickOutside)
  document.addEventListener('keydown', handleEscape)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('contextmenu', handleClickOutside)
  document.removeEventListener('keydown', handleEscape)
})
</script>
