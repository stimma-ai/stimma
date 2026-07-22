<script setup lang="ts">
import { computed } from 'vue';
import type { EditorContext } from '@/types/plugins';
import type { AnnotateTool } from '@/types/shapes';
import type { RetouchTool } from '@/types/editor';
import type { IconName } from '@/components/icons';
import Icon from '@/components/icons/Icon.vue';

const props = defineProps<{
  activePlugin: string | null;
  editorContext: EditorContext;
}>();

// ============================================
// ANNOTATE TOOLS
// ============================================
// Main annotation tools
const annotateMainTools: { id: AnnotateTool; icon: IconName; label: string }[] = [
  { id: 'sharpie', icon: 'pencil', label: 'Draw' },
  { id: 'arrow', icon: 'arrowUpRight', label: 'Arrow' },
  { id: 'text', icon: 'type', label: 'Text' },
  { id: 'redact', icon: 'redact', label: 'Redact' },
];

const annotateShapeTools: { id: AnnotateTool; icon: IconName; label: string }[] = [
  { id: 'line', icon: 'minus', label: 'Line' },
  { id: 'rectangle', icon: 'square', label: 'Rectangle' },
  { id: 'ellipse', icon: 'circle', label: 'Ellipse' },
  { id: 'star', icon: 'star', label: 'Star' },
  { id: 'polygon', icon: 'polygon', label: 'Polygon' },
];

const annotateActiveTool = computed(() => props.editorContext.state.activeTool);

function selectAnnotateTool(toolId: string) {
  props.editorContext.updateState({ activeTool: toolId as AnnotateTool });
}

// ============================================
// RETOUCH TOOLS
// ============================================
const retouchSelectionTools: { id: RetouchTool; icon: IconName; label: string }[] = [
  { id: 'marquee-rect', icon: 'squareDashed', label: 'Rect' },
  { id: 'marquee-ellipse', icon: 'circleDashed', label: 'Ellipse' },
  { id: 'lasso', icon: 'lasso', label: 'Lasso' },
  { id: 'magnetic-lasso', icon: 'magnet', label: 'Magnetic' },
];

const retouchPaintTools: { id: RetouchTool; icon: IconName; label: string }[] = [
  { id: 'paint', icon: 'paintbrush', label: 'Paint' },
  { id: 'fill', icon: 'fill', label: 'Fill' },
];

const retouchCloneTools: { id: RetouchTool; icon: IconName; label: string }[] = [
  { id: 'clone', icon: 'stamp', label: 'Clone' },
  { id: 'patch', icon: 'bandage', label: 'Patch' },
  { id: 'spot-heal', icon: 'circle', label: 'Spot' },
];

const retouchAdjustTools: { id: RetouchTool; icon: IconName; label: string }[] = [
  { id: 'dodge', icon: 'sun', label: 'Dodge' },
  { id: 'burn', icon: 'moon', label: 'Burn' },
  { id: 'sponge', icon: 'sponge', label: 'Sponge' },
  { id: 'blur-brush', icon: 'droplet', label: 'Blur' },
  { id: 'sharpen-brush', icon: 'focus', label: 'Sharpen' },
];

const retouchActiveTool = computed(() => props.editorContext.state.retouchTool);

function selectRetouchTool(toolId: string) {
  props.editorContext.updateState({
    retouchTool: toolId as RetouchTool,
    activeTool: toolId as RetouchTool,
  });
}

// ============================================
// UI STATE
// ============================================
const showAnnotateTools = computed(() => props.activePlugin === 'annotate');
const showRetouchTools = computed(() => props.activePlugin === 'retouch');
</script>

<template>
  <div class="stimma-tool-sidebar" v-if="showAnnotateTools || showRetouchTools">
    <!-- Annotate Tools -->
    <template v-if="showAnnotateTools">
      <!-- Main Tools: Draw, Arrow, Text, Redact -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in annotateMainTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': annotateActiveTool === tool.id }"
          :title="tool.label"
          @click="selectAnnotateTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>

      <div class="stimma-tool-sidebar__separator" />

      <!-- Shape Tools -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in annotateShapeTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': annotateActiveTool === tool.id }"
          :title="tool.label"
          @click="selectAnnotateTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>
    </template>

    <!-- Retouch Tools -->
    <template v-if="showRetouchTools">
      <!-- Paint / Fill -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in retouchPaintTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': retouchActiveTool === tool.id }"
          :title="tool.label"
          @click="selectRetouchTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>

      <div class="stimma-tool-sidebar__separator" />

      <!-- Selection Tools -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in retouchSelectionTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': retouchActiveTool === tool.id }"
          :title="tool.label"
          @click="selectRetouchTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>

      <div class="stimma-tool-sidebar__separator" />

      <!-- Clone / Patch -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in retouchCloneTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': retouchActiveTool === tool.id }"
          :title="tool.label"
          @click="selectRetouchTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>

      <div class="stimma-tool-sidebar__separator" />

      <!-- Adjust Tools -->
      <div class="stimma-tool-sidebar__group">
        <button
          v-for="tool in retouchAdjustTools"
          :key="tool.id"
          class="stimma-tool-sidebar__tool"
          :class="{ 'stimma-tool-sidebar__tool--active': retouchActiveTool === tool.id }"
          :title="tool.label"
          @click="selectRetouchTool(tool.id)"
        >
          <Icon :name="tool.icon" :size="18" />
          <span class="stimma-tool-sidebar__tool-label">{{ tool.label }}</span>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stimma-tool-sidebar {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--stimma-spacing-md);
  padding: var(--stimma-spacing-xs) var(--stimma-spacing-sm);
  background-color: rgb(var(--stimma-color-foreground) / 0.02);
  border-bottom: 1px solid rgb(var(--stimma-color-foreground) / 0.1);
  flex-shrink: 0;

  /* Enable container queries */
  container-type: inline-size;
  container-name: toolbar;

  /* Remove scrollbar, let wrapping handle overflow */
  flex-wrap: wrap;
  row-gap: var(--stimma-spacing-xs);
}

.stimma-tool-sidebar__section {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--stimma-spacing-xs);
}

.stimma-tool-sidebar__section-title {
  font-size: 9px;
  font-weight: 600;
  color: rgb(var(--stimma-color-foreground) / 0.5);
  padding: 0 4px;
  white-space: nowrap;
}

.stimma-tool-sidebar__tools {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 2px;
}

.stimma-tool-sidebar__group {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 2px;
}

.stimma-tool-sidebar__separator {
  width: 1px;
  height: 32px;
  background-color: rgb(var(--stimma-color-foreground) / 0.15);
  flex-shrink: 0;
}

.stimma-tool-sidebar__tool {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 4px 8px;
  border-radius: var(--stimma-border-radius);
  background-color: transparent;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  min-width: 48px;
}

.stimma-tool-sidebar__tool:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.08);
}

.stimma-tool-sidebar__tool--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-tool-sidebar__tool-label {
  font-size: 9px;
  font-weight: 500;
  text-align: center;
  line-height: 1.1;
  opacity: 0.7;
}

.stimma-tool-sidebar__tool--active .stimma-tool-sidebar__tool-label {
  opacity: 1;
}

/* Scale down at medium narrow widths */
@container toolbar (max-width: 800px) {
  .stimma-tool-sidebar {
    gap: var(--stimma-spacing-sm);
  }

  .stimma-tool-sidebar__tool {
    min-width: 42px;
    padding: 3px 6px;
  }

  .stimma-tool-sidebar__tool :deep(svg) {
    width: 16px;
    height: 16px;
  }

  .stimma-tool-sidebar__separator {
    height: 28px;
  }
}

/* Scale down more at narrow widths */
@container toolbar (max-width: 600px) {
  .stimma-tool-sidebar {
    gap: var(--stimma-spacing-xs);
  }

  .stimma-tool-sidebar__group {
    gap: 1px;
  }

  .stimma-tool-sidebar__tool {
    min-width: 36px;
    padding: 3px 4px;
    gap: 1px;
  }

  .stimma-tool-sidebar__tool :deep(svg) {
    width: 14px;
    height: 14px;
  }

  .stimma-tool-sidebar__tool-label {
    font-size: 8px;
  }

  .stimma-tool-sidebar__separator {
    height: 24px;
  }
}
</style>

