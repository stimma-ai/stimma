<script setup lang="ts">
import {
  ref,
  computed,
  onMounted,
  onUnmounted,
  watch,
  nextTick,
  provide,
} from 'vue';
import type {
  EditorState,
  EditorSettings,
  ImageSource,
  ExportOptions,
  LoadResult,
  ProcessResult,
  Shape,
} from '@/types';
import type { StimmaPlugin } from '@/types/plugins';
import { useEditor } from '@/composables/useEditor';
import { useInteraction } from '@/composables/useInteraction';
import { useAnnotation } from '@/composables/useAnnotation';
import { useRetouch } from '@/plugins/retouch/composables/useRetouch';
import { useKeyboard } from '@/composables/useKeyboard';
import { useImageWriter } from '@/composables/useImageWriter';
import { useSettingsPersistence } from '@/composables/useSettingsPersistence';
import {
  isEditorDebugEnabled,
  logEditorDebug,
  nextEditorDebugSession,
} from '@/utils/editorDebug';

import EditorCanvas from './EditorCanvas.vue';
import EditorToolbar from './EditorToolbar.vue';
import PluginTabs from './PluginTabs.vue';
import PluginPanel from './PluginPanel.vue';
import ToolSidebar from './ToolSidebar.vue';
import RetouchOverlay from '@/plugins/retouch/RetouchOverlay.vue';
// Note: InlineTextEditor removed - text editing is now done directly on canvas

// Props
const props = withDefaults(
  defineProps<{
    src?: ImageSource;
    imageState?: Partial<EditorState>;
    plugins?: StimmaPlugin[];
    theme?: 'light' | 'dark' | 'auto';
    disabled?: boolean;
    initialSettings?: Partial<EditorSettings>;
    /** Prefix for localStorage key (e.g., 'myapp-' results in key 'myapp-stimma-settings') */
    storagePrefix?: string;
  }>(),
  {
    plugins: () => [],
    theme: 'light',
    disabled: false,
    storagePrefix: '',
  }
);

// Emits
const emit = defineEmits<{
  (e: 'load-start'): void;
  (e: 'load', result: LoadResult): void;
  (e: 'load-error', error: Error): void;
  (e: 'process-start'): void;
  (e: 'process', result: ProcessResult): void;
  (e: 'process-error', error: Error): void;
  (e: 'update', state: EditorState): void;
  (e: 'update:imageState', state: EditorState): void;
  (e: 'close'): void;
  (e: 'revert'): void;
}>();

// Editor state management
const editor = useEditor(props.plugins);

// Settings persistence (automatic localStorage save/restore)
const settingsPersistence = useSettingsPersistence(props.storagePrefix);
editor.setSettingsPersistence(settingsPersistence);
editor.setStoragePrefix(props.storagePrefix);

// Load persisted settings first (so initialSettings prop can override)
const persistedSettings = settingsPersistence.loadSettings();
if (persistedSettings) {
  editor.updateState(persistedSettings);
}

// Restore last active plugin from persistence
const lastPlugin = settingsPersistence.getLastActivePlugin();
if (lastPlugin) {
  editor.setActivePlugin(lastPlugin);
}

// Apply initial settings if provided (overrides persisted values)
if (props.initialSettings) {
  editor.updateState(props.initialSettings);
}

// Image writer for export
const imageWriter = useImageWriter();

// Canvas ref from child component
const canvasComponentRef = ref<InstanceType<typeof EditorCanvas> | null>(null);

// Create a ref for the canvas element that we'll update when child mounts
const canvasElementRef = ref<HTMLCanvasElement | null>(null);

// Render trigger for forcing canvas redraws on stroke end (full reprocessing)
const renderTrigger = ref(0);
// Lightweight trigger for live retouch rendering during active strokes (no reprocessing)
const retouchDrawTrigger = ref(0);
const isRestoringProject = ref(false);
const debugEnabled = isEditorDebugEnabled();
const activeRestoreSession = ref<number | null>(null);

function debugLog(event: string, details: Record<string, unknown> = {}) {
  if (!debugEnabled) return;
  logEditorDebug('StimmaEditor', event, {
    restoreSession: activeRestoreSession.value,
    ...details,
  });
}

function requestRender() {
  // When called from useRetouch (any tool interaction), bypass Vue reactivity
  // and render synchronously. The caller is already RAF-gated, so this avoids:
  // - Vue watcher overhead from incrementing retouchDrawTrigger
  // - Double-RAF scheduling (extra frame of latency)
  // - ~60ms/s of cancelAnimationFrame/requestAnimationFrame overhead
  if (canvasComponentRef.value?.renderImmediate) {
    canvasComponentRef.value.renderImmediate();
    return;
  }
  retouchDrawTrigger.value++;
}
function requestFullRender() {
  renderTrigger.value++;
}

// Interaction handling
const interaction = useInteraction(
  canvasElementRef,
  editor.viewTransform,
  computed(() => editor.state.value.imageSize),
  editor.canvasSize,
  (panX, panY) => editor.setPan(panX, panY),
  (zoom) => editor.setZoom(zoom)
);

// Set up crop interaction callback
interaction.setCropCallback(
  (crop) => {
    editor.updateState({ crop });
  },
  () => ({
    activePlugin: editor.state.value.activePlugin,
    crop: editor.state.value.crop,
  })
);

// Annotation handling
const annotation = useAnnotation(
  canvasElementRef,
  editor.viewTransform,
  computed(() => editor.state.value.imageSize),
  editor.canvasSize,
  () => ({
    activeTool: editor.state.value.activeTool as any,
    annotations: editor.state.value.annotations,
    selectedShapeId: editor.state.value.selectedShapeId,
    annotateStrokeColor: editor.state.value.annotateStrokeColor,
    annotateFillColor: editor.state.value.annotateFillColor,
    annotateStrokeWidth: editor.state.value.annotateStrokeWidth,
    annotateBrushSettings: editor.state.value.annotateBrushSettings,
    annotateIsEraser: editor.state.value.annotateIsEraser,
    annotatePenId: editor.state.value.annotatePenId,
    // Text tool settings
    annotateTextFontFamily: editor.state.value.annotateTextFontFamily,
    annotateTextFontSize: editor.state.value.annotateTextFontSize,
    annotateTextFontWeight: editor.state.value.annotateTextFontWeight,
    annotateTextFontStyle: editor.state.value.annotateTextFontStyle,
    annotateTextAlign: editor.state.value.annotateTextAlign,
    annotateTextColor: editor.state.value.annotateTextColor,
    annotateTextBgColor: editor.state.value.annotateTextBgColor,
    annotateTextBackgroundPadding: editor.state.value.annotateTextBackgroundPadding,
    annotateTextBackgroundCornerRadius: editor.state.value.annotateTextBackgroundCornerRadius,
    // Text effect settings
    annotateTextEffect: editor.state.value.annotateTextEffect,
    annotateTextGlowIntensity: editor.state.value.annotateTextGlowIntensity,
    annotateTextGradientColors: editor.state.value.annotateTextGradientColors ? [...editor.state.value.annotateTextGradientColors] : undefined,
    annotateTextGradientDirection: editor.state.value.annotateTextGradientDirection,
    annotateTextShadowDirection: editor.state.value.annotateTextShadowDirection,
    annotateTextShadowLength: editor.state.value.annotateTextShadowLength,
    annotateTextShadowColor: editor.state.value.annotateTextShadowColor,
    annotateTextGlitchIntensity: editor.state.value.annotateTextGlitchIntensity,
    annotateTextKnockoutColor: editor.state.value.annotateTextKnockoutColor,
    // Redact settings
    annotateRedactBlockSize: editor.state.value.annotateRedactBlockSize,
    // Polygon settings
    annotatePolygonSides: editor.state.value.annotatePolygonSides,
    // Shape style settings
    annotateShapeEffect: editor.state.value.annotateShapeEffect,
    annotateGlowIntensity: editor.state.value.annotateGlowIntensity,
    annotateGradientColors: editor.state.value.annotateGradientColors ? [...editor.state.value.annotateGradientColors] : undefined,
    annotateGradientDirection: editor.state.value.annotateGradientDirection,
  }),
  (partial) => editor.updateState(partial as any),
  (action) => editor.pushHistory(action)
);

// ID of text shape being edited - null means no text shape should be hidden
// (Canvas-based editing shows cursor on the shape itself)
const editingTextShapeId = computed(() => {
  // No longer hide the shape during editing since we render cursor on it
  return null;
});

// Text edit state from annotation for canvas rendering (used in template)
const textEditState = computed(() => annotation.textEditState.value);

// Retouch handling
const retouch = useRetouch(
  canvasElementRef,
  editor.viewTransform,
  computed(() => editor.state.value.imageSize),
  editor.canvasSize,
  () => ({
    retouchTool: editor.state.value.retouchTool,
    retouchBrushSettings: editor.state.value.retouchBrushSettings,
    retouchCloneSource: editor.state.value.retouchCloneSource,
    retouchCloneOffset: editor.state.value.retouchCloneOffset,
    selectionFeather: editor.state.value.selectionFeather,
    wandTolerance: editor.state.value.wandTolerance,
    selectionMode: editor.state.value.selectionMode,
    dodgeBurnExposure: editor.state.value.dodgeBurnExposure,
    dodgeBurnRange: editor.state.value.dodgeBurnRange,
    spongeFlow: editor.state.value.spongeFlow,
    spongeMode: editor.state.value.spongeMode,
    blurSharpenStrength: editor.state.value.blurSharpenStrength,
    patchBlendWidth: editor.state.value.patchBlendWidth,
    retouchForegroundColor: editor.state.value.retouchForegroundColor,
    retouchBackgroundColor: editor.state.value.retouchBackgroundColor,
    // Magnetic lasso settings
    magneticLassoWidth: editor.state.value.magneticLassoWidth,
    magneticLassoContrast: editor.state.value.magneticLassoContrast,
    // Image transforms for coordinate conversion
    rotation: editor.state.value.rotation,
    rotation90: editor.state.value.rotation90,
    flipX: editor.state.value.flipX,
    flipY: editor.state.value.flipY,
  }),
  () => {
    // Get the source canvas (processed image without retouch layer)
    // This returns the base image with color/effects applied, at original size
    return canvasComponentRef.value?.getProcessedImageCanvas?.() ?? null;
  },
  (partial) => editor.updateState(partial as any),
  (action) => editor.pushHistoryImmediate(action),
  requestRender,
  requestFullRender
);

// When retouch drawing ends, trigger a full render to bake the retouch layer into the processed image
watch(
  () => retouch.isDrawing.value,
  (drawing, wasDrawing) => {
    if (!drawing && wasDrawing) {
      requestFullRender();
    }
  }
);

// Watch for canvas component ref changes and extract the actual canvas element
// Note: Vue's defineExpose automatically unwraps refs, so canvasRef is already HTMLCanvasElement
watch(
  () => canvasComponentRef.value?.canvasRef,
  (canvas) => {
    canvasElementRef.value = canvas ?? null;
  },
  { immediate: true }
);

// Undo/redo with retouch canvas restoration
// MUST be synchronous — an await would create a microtask boundary that
// flushes Vue watchers (50+ property watcher, deep emit watcher, etc.)
// BEFORE requestFullRender() runs, causing a redundant watcher+render cycle.
// restoreFromState is synchronous when data is HTMLCanvasElement (the undo/redo case).
function handleUndo() {
  const result = editor.undo();
  if (result) {
    restoreRetouchAfterHistory();
    requestFullRender();
  }
}

function handleRedo() {
  const result = editor.redo();
  if (result) {
    restoreRetouchAfterHistory();
    requestFullRender();
  }
}

// Keyboard shortcuts
useKeyboard({
  onUndo: () => handleUndo(),
  onRedo: () => handleRedo(),
  onEscape: () => {
    editor.updateState({ selectedShapeId: null });
  },
  onDelete: () => {
    const activePlugin = editor.state.value.activePlugin;

    // Retouch: clear selection to background color
    if (activePlugin === 'retouch' && retouch.hasSelection()) {
      retouch.clearPixels(editor.state.value.retouchBackgroundColor);
      return;
    }

    // Annotate: delete selected shape
    const selectedId = editor.state.value.selectedShapeId;
    if (selectedId && activePlugin === 'annotate') {
      const annotations = editor.state.value.annotations.filter(s => s.id !== selectedId);
      editor.updateState({ annotations, selectedShapeId: null });
      editor.pushHistory('Delete shape');
    }
  },
  isEditingText: () => annotation.isEditingTextOnCanvas(),
});

// Computed
const themeClass = computed(() => {
  if (props.theme === 'dark') return 'stimma-editor--dark';
  if (props.theme === 'auto') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'stimma-editor--dark'
      : '';
  }
  return '';
});

const isDarkTheme = computed(() => themeClass.value === 'stimma-editor--dark');
provide('stimmaThemeIsDark', isDarkTheme);

const isLoading = computed(
  () => editor.imageLoader.isLoading.value || imageWriter.isProcessing.value
);

const activePlugin = computed(() =>
  props.plugins.find((p) => p.id === editor.state.value.activePlugin)
);

const editorContext = computed(() => {
  const ctx = editor.createEditorContext();
  // Add retouch operations if retouch plugin is active
  if (editor.state.value.activePlugin === 'retouch') {
    ctx.retouch = {
      clearSelection: () => retouch.clearSelection(),
      fillSelection: (color) => retouch.fillSelection(color),
      clearPixels: (bgColor) => retouch.clearPixels(bgColor),
      featherSelection: (radius) => retouch.featherSelection(radius),
      invertSelection: () => retouch.invertSelection(),
      hasSelection: () => retouch.hasSelection(),
    };
  }
  return ctx;
});

// Cursor style based on active plugin and tool
const cursorStyle = computed(() => {
  if (editor.state.value.activePlugin === 'annotate') {
    // Use annotation's cursor style (handles selection, resize, etc.)
    return annotation.cursorStyle.value;
  }
  if (editor.state.value.activePlugin === 'retouch') {
    return retouch.cursorStyle.value;
  }
  return interaction.cursorStyle.value;
});

// Retouch canvas for rendering
const retouchCanvas = computed(() => retouch.getRetouchCanvas());

// Whether retouch is actively drawing (for two-tier rendering optimization)
const isRetouchDrawing = computed(() =>
  editor.state.value.activePlugin === 'retouch' && retouch.isDrawing.value
);

// Selection preview for overlay
const selectionPreview = computed(() => {
  if (!retouch.isDrawingSelection.value) return null;

  const state = editor.state.value;
  const tool = state.retouchTool;

  if (tool === 'marquee-rect' && retouch.selectionDrawingStartPoint.value) {
    return {
      type: 'rect' as const,
      startPoint: retouch.selectionDrawingStartPoint.value,
      currentPoint: retouch.selectionDrawingCurrentPoint.value || retouch.selectionDrawingStartPoint.value,
    };
  }
  if (tool === 'marquee-ellipse' && retouch.selectionDrawingStartPoint.value) {
    return {
      type: 'ellipse' as const,
      startPoint: retouch.selectionDrawingStartPoint.value,
      currentPoint: retouch.selectionDrawingCurrentPoint.value || retouch.selectionDrawingStartPoint.value,
    };
  }
  if (tool === 'lasso') {
    const points = retouch.selectionDrawingPoints.value;
    if (points.length === 0) return null;
    return {
      type: 'lasso' as const,
      startPoint: points[0],
      currentPoint: points[points.length - 1],
      points,
    };
  }
  return null;
});

// Patch tool state for overlay
const isPatchDragging = computed(() => retouch.isPatchDragging.value);
const isPatchDrawing = computed(() => retouch.isPatchDrawing.value);
const patchDragOffset = computed(() => {
  if (!retouch.patchDragStart.value || !retouch.patchDragCurrent.value) return null;
  return {
    x: retouch.patchDragCurrent.value.x - retouch.patchDragStart.value.x,
    y: retouch.patchDragCurrent.value.y - retouch.patchDragStart.value.y,
  };
});
const patchDrawingPoints = computed(() => retouch.patchDrawingPoints.value);

// Magnetic lasso state for overlay
const isMagneticLassoActive = computed(() => retouch.isMagneticLassoActive.value);
const magneticLassoAnchors = computed(() => retouch.magneticLassoAnchors.value);
const magneticLassoPathSegments = computed(() => retouch.magneticLassoPathSegments.value);
const magneticLassoPreviewPath = computed(() => retouch.magneticLassoPreviewPath.value);
const isMagneticLassoNearStart = computed(() => retouch.isMagneticLassoNearStart.value);

// Load image when src prop changes
watch(
  () => props.src,
  async (newSrc) => {
    if (newSrc) {
      emit('load-start');
      try {
        const result = await editor.loadImage(newSrc);
        emit('load', result);
      } catch (err) {
        emit('load-error', err as Error);
      }
    }
  },
  { immediate: true }
);

// Emit state updates
// No { deep: true } — updateState/setState always replace state.value (new reference),
// so the watcher fires on every change. deep:true would force Vue to traverse()
// the entire state tree (annotations, shapes, points, etc.) on every evaluation.
watch(
  () => editor.state.value,
  (state) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:state', {
        activePlugin: state.activePlugin,
        activeTool: state.activeTool,
        retouchTool: state.retouchTool,
        imageWidth: state.imageSize?.width ?? null,
        imageHeight: state.imageSize?.height ?? null,
        suppressed: isRestoringProject.value,
      });
    }
    if (isRestoringProject.value) {
      return;
    }
    emit('update', state as EditorState);
    emit('update:imageState', state as EditorState);
  }
);

// Methods
function handleRevert() {
  editor.revert();
  emit('revert');
}

function handleCanvasResize(size: { width: number; height: number }) {
  editor.setCanvasSize(size);
}

function handleResetRotation() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const annotations = editor.state.value.annotations.map((s) =>
    s.id === selectedId ? { ...s, rotation: 0 } : s
  );
  editor.updateState({ annotations });
  editor.pushHistory('Reset rotation');
}

function handleDuplicate() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const shape = editor.state.value.annotations.find((s) => s.id === selectedId);
  if (!shape) return;

  // Create a deep copy with a new ID and slight offset
  const newShape = structuredClone(shape) as Shape;
  newShape.id = `shape-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

  // Offset the duplicate slightly
  if ('x' in newShape) {
    (newShape as any).x += 0.02;
    (newShape as any).y += 0.02;
  }
  if ('x1' in newShape && 'x2' in newShape) {
    (newShape as any).x1 += 0.02;
    (newShape as any).y1 += 0.02;
    (newShape as any).x2 += 0.02;
    (newShape as any).y2 += 0.02;
  }
  if ('points' in newShape && Array.isArray((newShape as any).points)) {
    (newShape as any).points = (newShape as any).points.map((p: any) => ({
      x: p.x + 0.02,
      y: p.y + 0.02,
    }));
  }

  const annotations = [...editor.state.value.annotations, newShape];
  editor.updateState({ annotations, selectedShapeId: newShape.id });
  editor.pushHistory('Duplicate shape');
}

function handleDeleteShape() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const annotations = editor.state.value.annotations.filter((s) => s.id !== selectedId);
  editor.updateState({ annotations, selectedShapeId: null });
  editor.pushHistory('Delete shape');
}

async function loadProjectWithRetouch(project: any) {
  const retouchData = project?.state?.retouchLayerData ?? null;
  const selectionData = project?.state?.selectionMaskData ?? null;

  activeRestoreSession.value = nextEditorDebugSession('editor-restore');
  isRestoringProject.value = true;
  try {
    debugLog('restore:start', {
      hasRetouchData: !!retouchData,
      retouchDataType: typeof retouchData,
      hasSelectionData: !!selectionData,
      imageWidth: project?.imageSize?.width ?? null,
      imageHeight: project?.imageSize?.height ?? null,
      activePlugin: project?.state?.activePlugin ?? null,
      retouchTool: project?.state?.retouchTool ?? null,
    });
    await editor.loadProject(project);
    debugLog('restore:editor-loadProject-done', {
      stateActivePlugin: editor.state.value.activePlugin,
      stateRetouchTool: editor.state.value.retouchTool,
    });
    if (project?.imageSize?.width && project?.imageSize?.height) {
      retouch.initLayers(project.imageSize);
      debugLog('restore:init-retouch-layers', {
        width: project.imageSize.width,
        height: project.imageSize.height,
      });
    }
    await nextTick();
    debugLog('restore:next-tick');
    await retouch.restoreFromState(
      retouchData as HTMLCanvasElement | string | null,
      selectionData as HTMLCanvasElement | string | null
    );
    debugLog('restore:retouch-restore-done', {
      hasRetouchCanvas: !!retouch.getRetouchCanvas(),
      hasSelectionCanvas: !!retouch.getSelectionCanvas(),
    });
    requestFullRender();
    debugLog('restore:request-full-render');
  } finally {
    isRestoringProject.value = false;
    debugLog('restore:end');
    activeRestoreSession.value = null;
  }
}

async function serializeProjectWithRetouch(options?: {
  name?: string;
  includeThumbnail?: boolean;
  thumbnailMaxSize?: number;
  includeHistory?: boolean;
}) {
  const retouchSnapshot = retouch.createStateSnapshot();
  return editor.serializeState(
    {
      ...editor.state.value,
      ...retouchSnapshot,
    } as EditorState,
    options
  );
}

function handleBringToFront() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const shape = editor.state.value.annotations.find((s) => s.id === selectedId);
  if (!shape) return;

  const annotations = editor.state.value.annotations.filter((s) => s.id !== selectedId);
  annotations.push(shape);
  editor.updateState({ annotations });
  editor.pushHistory('Bring to front');
}

function handleSendToBack() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const shape = editor.state.value.annotations.find((s) => s.id === selectedId);
  if (!shape) return;

  const annotations = editor.state.value.annotations.filter((s) => s.id !== selectedId);
  annotations.unshift(shape);
  editor.updateState({ annotations });
  editor.pushHistory('Send to back');
}

function handleEditText() {
  const selectedId = editor.state.value.selectedShapeId;
  if (!selectedId) return;

  const shape = editor.state.value.annotations.find((s) => s.id === selectedId);
  if (!shape || shape.type !== 'text') return;

  // Enter canvas-based text editing mode
  annotation.startTextEditing(shape.id);
}

// Setup interaction listeners after child components mount
onMounted(async () => {
  await nextTick();
  await nextTick(); // Double nextTick to ensure child refs are ready
  interaction.setupListeners();

  // Setup annotation listeners if annotate plugin is active
  if (editor.state.value.activePlugin === 'annotate') {
    annotation.setupListeners();
  }

  // Setup retouch listeners if retouch plugin is active
  if (editor.state.value.activePlugin === 'retouch') {
    retouch.setupListeners();
  }
});

// Initialize retouch layers when image loads
// Watch individual dimension values, not the imageSize object reference —
// undo replaces state.value which creates a new imageSize object even when
// dimensions are identical, and we must not re-init layers on undo.
watch(
  [() => editor.state.value.imageSize?.width, () => editor.state.value.imageSize?.height],
  ([w, h]) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:image-size', {
        width: w ?? null,
        height: h ?? null,
      });
    }
    if (w && h) {
      retouch.initLayers({ width: w, height: h });
      if (activeRestoreSession.value !== null) {
        debugLog('watch:image-size:init-retouch-layers', {
          width: w,
          height: h,
        });
      }
    }
  },
  { immediate: true }
);

// Watch for plugin changes to setup/cleanup listeners
watch(
  () => editor.state.value.activePlugin,
  (newPlugin, oldPlugin) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:active-plugin', {
        newPlugin: newPlugin ?? null,
        oldPlugin: oldPlugin ?? null,
      });
    }
    settingsPersistence.setLastActivePlugin(newPlugin ?? null);
    settingsPersistence.saveSettingsImmediate(getCurrentSettings());

    if (oldPlugin === 'annotate') {
      annotation.cleanupListeners();
    }
    if (oldPlugin === 'retouch') {
      retouch.cleanupListeners();
    }
    if (newPlugin === 'annotate') {
      annotation.setupListeners();
    }
    if (newPlugin === 'retouch') {
      retouch.setupListeners();
    }
  }
);

// Watch for tool changes to stop text editing and track last tool
watch(
  () => editor.state.value.activeTool,
  (newTool) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:active-tool', {
        activePlugin: editor.state.value.activePlugin,
        newTool: newTool ?? null,
      });
    }
    // Stop text editing when tool changes (commit changes)
    if (annotation.isEditingTextOnCanvas()) {
      annotation.commitText();
    }

    // Track last annotate tool for persistence
    if (editor.state.value.activePlugin === 'annotate' && newTool) {
      settingsPersistence.setLastAnnotateTool(newTool);
    }
  }
);

// Watch for retouch tool changes to track last tool
watch(
  () => editor.state.value.retouchTool,
  (newTool) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:retouch-tool', {
        activePlugin: editor.state.value.activePlugin,
        newTool: newTool ?? null,
      });
    }
    if (editor.state.value.activePlugin === 'retouch' && newTool) {
      settingsPersistence.setLastRetouchTool(newTool);
    }
  }
);

// Also watch for canvas element changes - setup retouch listeners when canvas becomes available
watch(
  canvasElementRef,
  (canvas) => {
    if (activeRestoreSession.value !== null) {
      debugLog('watch:canvas-element', {
        hasCanvas: !!canvas,
        activePlugin: editor.state.value.activePlugin,
      });
    }
    if (canvas && editor.state.value.activePlugin === 'retouch') {
      retouch.setupListeners();
    }
  }
);

// Helper to restore retouch canvas after undo/redo
// Called explicitly after history operations, not via watcher (to avoid sync/restore loops)
// Synchronous — from history, data is always HTMLCanvasElement (canvas snapshots).
function restoreRetouchAfterHistory() {
  const state = editor.state.value;
  retouch.restoreFromState(
    state.retouchLayerData as HTMLCanvasElement | string | null,
    state.selectionMaskData as HTMLCanvasElement | string | null
  );
}

// Helper to extract current settings for persistence
function getCurrentSettings(): EditorSettings {
  const s = editor.state.value;
  return {
    annotateStrokeColor: s.annotateStrokeColor,
    annotateFillColor: s.annotateFillColor,
    annotateStrokeWidth: s.annotateStrokeWidth,
    annotateBrushSettings: { ...s.annotateBrushSettings },
    annotateIsEraser: s.annotateIsEraser,
    annotatePenId: s.annotatePenId,
    // Universal shape style settings
    annotateShapeEffect: s.annotateShapeEffect,
    annotateGlowIntensity: s.annotateGlowIntensity,
    annotateGradientColors: [...s.annotateGradientColors],
    annotateGradientDirection: s.annotateGradientDirection,
    // Text settings
    annotateTextFontFamily: s.annotateTextFontFamily,
    annotateTextFontSize: s.annotateTextFontSize,
    annotateTextFontWeight: s.annotateTextFontWeight,
    annotateTextFontStyle: s.annotateTextFontStyle,
    annotateTextAlign: s.annotateTextAlign,
    annotateTextBackgroundPadding: s.annotateTextBackgroundPadding,
    annotateTextBackgroundCornerRadius: s.annotateTextBackgroundCornerRadius,
    annotateTextColor: s.annotateTextColor,
    annotateTextBgColor: s.annotateTextBgColor,
    annotateTextEffect: s.annotateTextEffect,
    annotateTextGlowIntensity: s.annotateTextGlowIntensity,
    annotateTextGlowColor: s.annotateTextGlowColor,
    annotateTextGradientColors: s.annotateTextGradientColors,
    annotateTextGradientDirection: s.annotateTextGradientDirection,
    annotateTextShadowDirection: s.annotateTextShadowDirection,
    annotateTextShadowLength: s.annotateTextShadowLength,
    annotateTextShadowColor: s.annotateTextShadowColor,
    annotateTextGlitchIntensity: s.annotateTextGlitchIntensity,
    annotateTextKnockoutColor: s.annotateTextKnockoutColor,
    annotateRedactBlockSize: s.annotateRedactBlockSize,
    annotatePolygonSides: s.annotatePolygonSides,
    // Retouch settings
    retouchBrushSettings: { ...s.retouchBrushSettings },
    selectionFeather: s.selectionFeather,
    wandTolerance: s.wandTolerance,
    dodgeBurnExposure: s.dodgeBurnExposure,
    dodgeBurnRange: s.dodgeBurnRange,
    spongeFlow: s.spongeFlow,
    spongeMode: s.spongeMode,
    blurSharpenStrength: s.blurSharpenStrength,
    retouchForegroundColor: { ...s.retouchForegroundColor },
    retouchBackgroundColor: { ...s.retouchBackgroundColor },
    patchBlendWidth: s.patchBlendWidth,
    magneticLassoWidth: s.magneticLassoWidth,
    magneticLassoContrast: s.magneticLassoContrast,
  };
}

// Watch for settings changes and auto-save (debounced via persistence)
// Use a JSON hash to avoid { deep: true } which causes Vue to wrap nested objects in Proxies
const settingsKey = computed(() => JSON.stringify(getCurrentSettings()));

watch(settingsKey, () => {
  if (activeRestoreSession.value !== null) {
    debugLog('watch:settings-key', {
      activePlugin: editor.state.value.activePlugin,
      activeTool: editor.state.value.activeTool,
      retouchTool: editor.state.value.retouchTool,
    });
  }
  settingsPersistence.saveSettings(getCurrentSettings());
});

onUnmounted(() => {
  interaction.cleanupListeners();
  annotation.cleanupListeners();
  retouch.cleanupListeners();
  settingsPersistence.cleanup();
});

// Expose public API
defineExpose({
  loadImage: (src: ImageSource) => editor.loadImage(src),
  processImage: (options?: Partial<ExportOptions>) => {
    const sourceImage = editor.getImageElement();
    if (!sourceImage) return Promise.reject(new Error('No image loaded'));
    return imageWriter.process(
      editor.state.value as EditorState,
      sourceImage,
      options,
      retouchCanvas.value
    );
  },
  // Alias for processImage - clearer naming for rasterization
  rasterize: (options?: Partial<ExportOptions>) => {
    const sourceImage = editor.getImageElement();
    if (!sourceImage) return Promise.reject(new Error('No image loaded'));
    return imageWriter.process(
      editor.state.value as EditorState,
      sourceImage,
      options,
      retouchCanvas.value
    );
  },
  getState: () => editor.state.value,
  setState: (state: Partial<EditorState>) => editor.updateState(state),
  undo: () => handleUndo(),
  redo: () => handleRedo(),
  revert: () => editor.revert(),
  getCanvas: () => canvasComponentRef.value?.canvasRef ?? null,
  // Serialization methods for save/load functionality
  serialize: (options?: { name?: string; includeThumbnail?: boolean; thumbnailMaxSize?: number; includeHistory?: boolean }) =>
    serializeProjectWithRetouch(options),
  loadProject: (project: any) => loadProjectWithRetouch(project),
  // Get current user settings for persistence
  getSettings: (): EditorSettings => getCurrentSettings(),
});
</script>

<template>
  <div
    class="stimma-editor"
    :class="[themeClass, { 'stimma-editor--loading': isLoading }]"
    role="application"
    aria-label="Image editor"
  >
    <!-- Main content area -->
    <div class="stimma-editor__main">
      <!-- Plugin tabs (left sidebar) -->
      <PluginTabs
        v-if="plugins.length > 0"
        :plugins="plugins"
        :active-plugin="editor.state.value.activePlugin"
        @select="editor.setActivePlugin"
      />

      <!-- Center column (toolbar + canvas) -->
      <div class="stimma-editor__center">
        <!-- Tool toolbar (top, for annotate/retouch tools) -->
        <ToolSidebar
          v-if="plugins.length > 0"
          :active-plugin="editor.state.value.activePlugin"
          :editor-context="editorContext"
        />

        <!-- Canvas wrapper for overlay positioning -->
        <div class="stimma-editor__canvas-wrapper">
        <!-- Canvas -->
        <EditorCanvas
          ref="canvasComponentRef"
          :state="(editor.state.value as EditorState)"
          :view-transform="editor.viewTransform.value"
          :source-image="editor.imageLoader.sourceImage.value"
          :cursor-style="cursorStyle"
          :view-mode="editor.viewMode.value"
          :is-animating="editor.isAnimating.value"
          :retouch-canvas="retouchCanvas"
          :render-trigger="renderTrigger"
          :retouch-draw-trigger="retouchDrawTrigger"
          :debug-session-id="activeRestoreSession"
          :is-retouch-drawing="isRetouchDrawing"
          :editing-text-shape-id="editingTextShapeId"
          :text-edit-state="textEditState"
          :hide-annotations="editor.state.value.activePlugin === 'retouch' && editor.state.value.hideAnnotationsInRetouch"
          @resize="handleCanvasResize"
          @reset-rotation="handleResetRotation"
          @duplicate="handleDuplicate"
          @delete="handleDeleteShape"
          @edit-text="handleEditText"
          @bring-to-front="handleBringToFront"
          @send-to-back="handleSendToBack"
          @pan="editor.setPan"
        />

        <!-- Retouch overlay (marching ants, clone source indicator, patch preview) -->
        <RetouchOverlay
          v-if="editor.state.value.activePlugin === 'retouch'"
          :editor="editorContext"
          :view-transform="editor.viewTransform.value"
          :canvas-size="editor.canvasSize.value"
          :marching-ants-paths="retouch.getMarchingAntsPaths()"
          :clone-source="editor.state.value.retouchCloneSource"
          :current-brush-size="editor.state.value.retouchBrushSettings.size"
          :is-drawing-selection="retouch.isDrawingSelection.value"
          :selection-preview="selectionPreview"
          :is-patch-dragging="isPatchDragging"
          :is-patch-drawing="isPatchDrawing"
          :patch-drag-offset="patchDragOffset"
          :patch-drawing-points="patchDrawingPoints"
          :is-magnetic-lasso-active="isMagneticLassoActive"
          :magnetic-lasso-anchors="magneticLassoAnchors"
          :magnetic-lasso-path-segments="magneticLassoPathSegments"
          :magnetic-lasso-preview-path="magneticLassoPreviewPath"
          :is-magnetic-lasso-near-start="isMagneticLassoNearStart"
          :debug-session-id="activeRestoreSession"
        />

        <!-- Text editing is now done directly on canvas -->
        </div>
      </div>

      <!-- Plugin panel -->
      <PluginPanel
        v-if="plugins.length > 0"
        :plugin="activePlugin"
        :editor-context="editorContext"
      />
    </div>

    <!-- Toolbar (bottom) -->
    <EditorToolbar
      :can-undo="editor.canUndo.value"
      :can-redo="editor.canRedo.value"
      :zoom="editor.viewTransform.value.zoom"
      :active-plugin="editor.state.value.activePlugin"
      :hide-annotations-in-retouch="editor.state.value.hideAnnotationsInRetouch"
      @undo="handleUndo"
      @redo="handleRedo"
      @revert="handleRevert"
      @zoom-in="editor.zoomIn"
      @zoom-out="editor.zoomOut"
      @zoom-reset="editor.resetZoom"
      @toggle-annotations="editor.updateState({ hideAnnotationsInRetouch: !editor.state.value.hideAnnotationsInRetouch })"
    >
      <template #toolbar-end>
        <slot name="toolbar-end" />
      </template>
    </EditorToolbar>

    <!-- Loading overlay -->
    <div v-if="isLoading" class="stimma-editor__loading">
      <div class="stimma-editor__spinner" />
    </div>

    <!-- Screen reader announcer -->
    <div
      id="stimma-announcer"
      class="stimma-announcer"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    />
  </div>
</template>
