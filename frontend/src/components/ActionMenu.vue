<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuRef"
      class="action-menu"
      :style="menuStyle"
      @click.stop
    >
      <div
        v-for="(action, index) in actions"
        :key="index"
        class="menu-item"
        :class="{ disabled: action.disabled, danger: action.danger, divider: action.divider || action.id === 'divider' }"
        @click="handleAction(action)"
      >
        <div v-if="action.divider || action.id === 'divider'" class="menu-divider" />
        <template v-else>
          <span v-if="action.icon" class="menu-icon" v-html="sanitizeSvg(action.icon)" />
          <span class="menu-label">{{ action.label }}</span>
          <span v-if="action.shortcut" class="menu-shortcut">{{ action.shortcut }}</span>
        </template>
      </div>
    </div>
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

<style scoped>
.action-menu {
  position: fixed;
  z-index: 9999;
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
  min-width: 200px;
  padding: 4px 0;
  animation: menuFadeIn 0.15s ease-out;
}

@keyframes menuFadeIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  transition: background-color 0.15s;
  user-select: none;
}

.menu-item:hover:not(.disabled):not(.divider) {
  background-color: var(--color-surface-raised);
}

.menu-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.menu-item.danger {
  color: #ef4444;
}

.menu-item.danger:hover:not(.disabled) {
  background-color: #7f1d1d;
}

.menu-item.divider {
  padding: 0;
  margin: 4px 0;
  cursor: default;
}

.menu-divider {
  height: 1px;
  background-color: var(--color-border);
  margin: 0 8px;
}

.menu-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.menu-icon :deep(svg) {
  width: 18px;
  height: 18px;
  color: currentColor;
}

.menu-label {
  flex: 1;
}

.menu-shortcut {
  color: #9ca3af;
  font-size: 0.75rem;
  margin-left: auto;
}
</style>
