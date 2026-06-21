<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import type { ViewTransform, Size } from '@/types';

const props = defineProps<{
  viewTransform: ViewTransform;
  imageSize: Size | null;
  canvasSize: Size;
}>();

const emit = defineEmits<{
  (e: 'pan', x: number, y: number): void;
}>();

// Dragging state
const isDraggingH = ref(false);
const isDraggingV = ref(false);
const dragStartMouse = ref({ x: 0, y: 0 });
const dragStartPan = ref({ x: 0, y: 0 });

// Hover state
const isHoveringH = ref(false);
const isHoveringV = ref(false);

// Calculate the visible bounds of the image in canvas space
const scrollInfo = computed(() => {
  if (!props.imageSize) {
    return { showH: false, showV: false, hThumb: { left: 0, width: 100 }, vThumb: { top: 0, height: 100 } };
  }

  const { zoom, panX, panY } = props.viewTransform;
  const imgW = props.imageSize.width * zoom;
  const imgH = props.imageSize.height * zoom;
  const canvasW = props.canvasSize.width;
  const canvasH = props.canvasSize.height;

  // Image bounds in canvas space (centered with pan offset)
  const imgLeft = (canvasW - imgW) / 2 + panX;
  const imgRight = imgLeft + imgW;
  const imgTop = (canvasH - imgH) / 2 + panY;
  const imgBottom = imgTop + imgH;

  // Total scrollable area (image + visible canvas area)
  const totalLeft = Math.min(0, imgLeft);
  const totalRight = Math.max(canvasW, imgRight);
  const totalTop = Math.min(0, imgTop);
  const totalBottom = Math.max(canvasH, imgBottom);

  const totalW = totalRight - totalLeft;
  const totalH = totalBottom - totalTop;

  // Calculate thumb position and size as percentage
  // Horizontal - visible region starts at 0, thumb shows relative position
  const hThumbWidth = Math.max(20, (canvasW / totalW) * 100);
  const hThumbLeft = ((-totalLeft) / totalW) * 100;

  // Vertical
  const vThumbHeight = Math.max(20, (canvasH / totalH) * 100);
  const vThumbTop = ((-totalTop) / totalH) * 100;

  // Only show scrollbar if image extends beyond canvas
  const showH = imgW > canvasW || imgLeft < 0 || imgRight > canvasW;
  const showV = imgH > canvasH || imgTop < 0 || imgBottom > canvasH;

  return {
    showH,
    showV,
    hThumb: { left: hThumbLeft, width: hThumbWidth },
    vThumb: { top: vThumbTop, height: vThumbHeight },
    totalW,
    totalH,
    totalLeft,
    totalTop,
  };
});

// Handle horizontal scrollbar drag
function onHMouseDown(event: MouseEvent) {
  event.preventDefault();
  isDraggingH.value = true;
  dragStartMouse.value = { x: event.clientX, y: event.clientY };
  dragStartPan.value = { x: props.viewTransform.panX, y: props.viewTransform.panY };
}

// Handle vertical scrollbar drag
function onVMouseDown(event: MouseEvent) {
  event.preventDefault();
  isDraggingV.value = true;
  dragStartMouse.value = { x: event.clientX, y: event.clientY };
  dragStartPan.value = { x: props.viewTransform.panX, y: props.viewTransform.panY };
}

function onMouseMove(event: MouseEvent) {
  if (!isDraggingH.value && !isDraggingV.value) return;

  const info = scrollInfo.value;
  if (!info.showH && !info.showV) return;

  let newPanX = dragStartPan.value.x;
  let newPanY = dragStartPan.value.y;

  if (isDraggingH.value && info.totalW !== undefined) {
    // Calculate how much mouse moved as percentage of track
    const trackWidth = props.canvasSize.width - 24; // Account for padding and corner
    const mouseDeltaPercent = ((event.clientX - dragStartMouse.value.x) / trackWidth) * 100;
    // Convert to pan delta (inverse relationship)
    const panDelta = -(mouseDeltaPercent / 100) * info.totalW;
    newPanX = dragStartPan.value.x + panDelta;
  }

  if (isDraggingV.value && info.totalH !== undefined) {
    const trackHeight = props.canvasSize.height - 24;
    const mouseDeltaPercent = ((event.clientY - dragStartMouse.value.y) / trackHeight) * 100;
    const panDelta = -(mouseDeltaPercent / 100) * info.totalH;
    newPanY = dragStartPan.value.y + panDelta;
  }

  emit('pan', newPanX, newPanY);
}

function onMouseUp() {
  isDraggingH.value = false;
  isDraggingV.value = false;
}

// Handle track clicks (jump to position)
function onHTrackClick(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  const clickPercent = (event.clientX - rect.left) / rect.width;
  const info = scrollInfo.value;

  if (info.totalW === undefined || info.totalLeft === undefined) return;

  // Calculate new pan to center viewport at clicked position
  const newPanX = -(clickPercent * info.totalW - props.canvasSize.width / 2) + info.totalLeft + props.canvasSize.width / 2;
  emit('pan', newPanX, props.viewTransform.panY);
}

function onVTrackClick(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  const clickPercent = (event.clientY - rect.top) / rect.height;
  const info = scrollInfo.value;

  if (info.totalH === undefined || info.totalTop === undefined) return;

  const newPanY = -(clickPercent * info.totalH - props.canvasSize.height / 2) + info.totalTop + props.canvasSize.height / 2;
  emit('pan', props.viewTransform.panX, newPanY);
}

onMounted(() => {
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
});

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove);
  window.removeEventListener('mouseup', onMouseUp);
});
</script>

<template>
  <div class="stimma-scrollbars">
    <!-- Horizontal scrollbar -->
    <div
      v-if="scrollInfo.showH"
      class="stimma-scrollbar stimma-scrollbar--horizontal"
      :class="{ 'stimma-scrollbar--active': isDraggingH || isHoveringH }"
      @mouseenter="isHoveringH = true"
      @mouseleave="isHoveringH = false"
      @click.self="onHTrackClick"
    >
      <div
        class="stimma-scrollbar__thumb"
        :style="{
          left: `${scrollInfo.hThumb.left}%`,
          width: `${scrollInfo.hThumb.width}%`,
        }"
        @mousedown="onHMouseDown"
      />
    </div>

    <!-- Vertical scrollbar -->
    <div
      v-if="scrollInfo.showV"
      class="stimma-scrollbar stimma-scrollbar--vertical"
      :class="{ 'stimma-scrollbar--active': isDraggingV || isHoveringV }"
      @mouseenter="isHoveringV = true"
      @mouseleave="isHoveringV = false"
      @click.self="onVTrackClick"
    >
      <div
        class="stimma-scrollbar__thumb"
        :style="{
          top: `${scrollInfo.vThumb.top}%`,
          height: `${scrollInfo.vThumb.height}%`,
        }"
        @mousedown="onVMouseDown"
      />
    </div>
  </div>
</template>

<style scoped>
.stimma-scrollbars {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 50;
}

.stimma-scrollbar {
  position: absolute;
  background: transparent;
  pointer-events: auto;
}

.stimma-scrollbar--horizontal {
  left: 4px;
  right: 16px;
  bottom: 4px;
  height: 8px;
}

.stimma-scrollbar--vertical {
  top: 4px;
  bottom: 16px;
  right: 4px;
  width: 8px;
}

.stimma-scrollbar__thumb {
  position: absolute;
  background: rgba(255, 255, 255, 0.3);
  border-radius: var(--stimma-border-radius-sm);
  transition: background-color 0.15s;
  cursor: pointer;
}

.stimma-scrollbar--horizontal .stimma-scrollbar__thumb {
  height: 100%;
  min-width: 24px;
}

.stimma-scrollbar--vertical .stimma-scrollbar__thumb {
  width: 100%;
  min-height: 24px;
}

.stimma-scrollbar--active .stimma-scrollbar__thumb,
.stimma-scrollbar__thumb:hover {
  background: rgba(255, 255, 255, 0.6);
}
</style>
