import { ref, computed, readonly, shallowRef, shallowReadonly } from 'vue';
import type { EditorState, ImageSource, ViewTransform, Size } from '@/types';
import type { StimmaPlugin, EditorContext } from '@/types/plugins';
import { DEFAULT_EDITOR_STATE, DEFAULT_VIEW_TRANSFORM } from '@/constants';
import { useHistory } from './useHistory';
import { useImageLoader } from './useImageLoader';
import { calculateFitZoom, calculateCropViewTransform } from '@/utils/canvas';
import {
  serializeProject,
  deserializeProject,
  type SerializedProject,
  type SerializeOptions,
} from '@/utils/serialization';
import type { SettingsPersistence } from './useSettingsPersistence';

/**
 * Easing function for smooth animations (ease-out cubic)
 */
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Animate between two view transforms
 */
function animateTransform(
  from: { zoom: number; panX: number; panY: number },
  to: { zoom: number; panX: number; panY: number },
  duration: number,
  onUpdate: (values: { zoom: number; panX: number; panY: number }) => void,
  onComplete: () => void
): () => void {
  const startTime = performance.now();
  let animationId: number | null = null;

  function tick(currentTime: number) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = easeOutCubic(progress);

    const zoom = from.zoom + (to.zoom - from.zoom) * eased;
    const panX = from.panX + (to.panX - from.panX) * eased;
    const panY = from.panY + (to.panY - from.panY) * eased;

    onUpdate({ zoom, panX, panY });

    if (progress < 1) {
      animationId = requestAnimationFrame(tick);
    } else {
      onComplete();
    }
  }

  animationId = requestAnimationFrame(tick);

  // Return cancel function
  return () => {
    if (animationId !== null) {
      cancelAnimationFrame(animationId);
    }
  };
}

/**
 * Main editor state composable
 */
export function useEditor(initialPlugins: StimmaPlugin[] = []) {
  // Core state
  // shallowRef: Vue tracks state.value replacement but does NOT deep-proxy
  // nested objects (annotations, shapes, points, crop, brushSettings, etc.).
  // This is safe because updateState/setState always replace state.value.
  const state = shallowRef<EditorState>({ ...DEFAULT_EDITOR_STATE });
  const viewTransform = ref<ViewTransform>({ ...DEFAULT_VIEW_TRANSFORM });
  const canvasSize = ref<Size>({ width: 800, height: 600 });
  const canvasRef = ref<HTMLCanvasElement | null>(null);

  // View mode: 'full' shows entire image (crop mode), 'crop' shows only crop region
  const viewMode = ref<'full' | 'crop'>('full');
  const isAnimating = ref(false);

  // Animation cancellation
  let cancelAnimation: (() => void) | null = null;

  // Plugins
  const plugins = ref<StimmaPlugin[]>(initialPlugins);
  const activePlugin = computed(() =>
    plugins.value.find((p) => p.id === state.value.activePlugin)
  );

  // Settings persistence (optional, set via setSettingsPersistence)
  let settingsPersistence: SettingsPersistence | null = null;

  // Storage prefix for localStorage keys (set externally)
  let storagePrefix = '';

  // Image loader
  const imageLoader = useImageLoader();

  // History manager
  const history = useHistory(
    () => state.value,
    (newState) => {
      state.value = newState;
    }
  );

  /**
   * Update state partially
   */
  function updateState(partial: Partial<EditorState>) {
    state.value = { ...state.value, ...partial };
  }

  /**
   * Set the entire state
   */
  function setState(newState: EditorState) {
    state.value = newState;
  }

  /**
   * Get current state
   */
  function getState(): EditorState {
    return state.value;
  }

  /**
   * Push current state to history
   */
  function pushHistory(action: string) {
    history.push(action);
  }

  function pushHistoryImmediate(action: string) {
    history.pushImmediate(action);
  }

  /**
   * Get canvas element
   */
  function getCanvas(): HTMLCanvasElement | null {
    return canvasRef.value;
  }

  /**
   * Get source image element
   */
  function getImageElement(): HTMLImageElement | null {
    return imageLoader.sourceImage.value;
  }

  /**
   * Create editor context for plugins
   */
  function createEditorContext(): EditorContext {
    return {
      state: state.value,
      updateState,
      pushHistory,
      getCanvas,
      getImageElement,
      storagePrefix,
    };
  }

  /**
   * Load an image into the editor
   */
  async function loadImage(source: ImageSource) {
    const result = await imageLoader.load(source);

    // Update state with new image
    updateState({
      src: source,
      imageSize: result.imageSize,
      // Reset crop to full image
      crop: {
        x: 0.5,
        y: 0.5,
        width: 1,
        height: 1,
        aspectRatio: null,
      },
      // Reset transforms
      rotation: 0,
      rotation90: 0,
      flipX: false,
      flipY: false,
    });

    // Calculate fit zoom
    const fitZoom = calculateFitZoom(result.imageSize, canvasSize.value);
    viewTransform.value = {
      ...DEFAULT_VIEW_TRANSFORM,
      zoom: fitZoom,
    };

    // Initialize history with loaded state
    history.clear();
    history.pushImmediate('Load image');

    return result;
  }

  /**
   * Set canvas size (called when container resizes)
   */
  function setCanvasSize(size: Size) {
    if (
      canvasSize.value.width === size.width &&
      canvasSize.value.height === size.height
    ) {
      return;
    }

    canvasSize.value = size;

    // Recalculate fit zoom if image is loaded
    if (state.value.imageSize) {
      const fitZoom = calculateFitZoom(state.value.imageSize, size);
      // Only update zoom if not manually zoomed
      if (viewTransform.value.zoom === 1 || viewTransform.value.zoom <= fitZoom) {
        if (viewTransform.value.zoom !== fitZoom) {
          viewTransform.value.zoom = fitZoom;
        }
      }
    }
  }

  /**
   * Transition to crop view (zoom to fit crop region)
   * Called when LEAVING crop mode - zooms into the crop region
   */
  function transitionToCropView() {
    if (!state.value.imageSize) return;

    // Cancel any running animation
    if (cancelAnimation) {
      cancelAnimation();
      cancelAnimation = null;
    }

    isAnimating.value = true;

    // Apply clipping immediately at start of animation
    viewMode.value = 'crop';

    // Store starting values
    const from = {
      zoom: viewTransform.value.zoom,
      panX: viewTransform.value.panX,
      panY: viewTransform.value.panY,
    };

    // Calculate target values (fit crop region)
    const to = calculateCropViewTransform(
      state.value.crop,
      state.value.imageSize,
      canvasSize.value
    );

    // Animate the transition
    cancelAnimation = animateTransform(
      from,
      to,
      300,
      (values) => {
        viewTransform.value = {
          ...viewTransform.value,
          zoom: values.zoom,
          panX: values.panX,
          panY: values.panY,
        };
      },
      () => {
        isAnimating.value = false;
        cancelAnimation = null;
      }
    );
  }

  /**
   * Transition to full view (show entire image)
   * Called when ENTERING crop mode - zooms out to show full image
   */
  function transitionToFullView() {
    if (!state.value.imageSize) return;

    // Cancel any running animation
    if (cancelAnimation) {
      cancelAnimation();
      cancelAnimation = null;
    }

    isAnimating.value = true;

    // Keep clipping during animation, remove at the end

    // Store starting values
    const from = {
      zoom: viewTransform.value.zoom,
      panX: viewTransform.value.panX,
      panY: viewTransform.value.panY,
    };

    // Calculate target values (fit full image)
    const fitZoom = calculateFitZoom(state.value.imageSize, canvasSize.value);
    const to = {
      zoom: fitZoom,
      panX: 0,
      panY: 0,
    };

    // Animate the transition
    cancelAnimation = animateTransform(
      from,
      to,
      300,
      (values) => {
        viewTransform.value = {
          ...viewTransform.value,
          zoom: values.zoom,
          panX: values.panX,
          panY: values.panY,
        };
      },
      () => {
        // Remove clipping at end of animation
        viewMode.value = 'full';
        isAnimating.value = false;
        cancelAnimation = null;
      }
    );
  }

  /**
   * Set active plugin
   */
  function setActivePlugin(pluginId: string) {
    const plugin = plugins.value.find((p) => p.id === pluginId);
    if (plugin) {
      const oldPlugin = state.value.activePlugin;
      const updates: Partial<EditorState> = { activePlugin: pluginId };

      // Set default tool for annotate plugin (use last selected if available)
      if (pluginId === 'annotate') {
        const lastTool = settingsPersistence?.getLastAnnotateTool() ?? 'sharpie';
        updates.activeTool = lastTool;
        updates.selectedShapeId = null;
      } else if (pluginId === 'retouch') {
        // Use last selected retouch tool if available
        const lastTool = settingsPersistence?.getLastRetouchTool() ?? null;
        updates.retouchTool = lastTool;
        updates.activeTool = null;
      } else {
        updates.activeTool = null;
      }

      updateState(updates);

      // Animate view transition
      if (oldPlugin === 'crop' && pluginId !== 'crop') {
        // Leaving crop mode - zoom to crop region
        transitionToCropView();
      } else if (oldPlugin !== 'crop' && pluginId === 'crop') {
        // Entering crop mode - show full image
        transitionToFullView();
      }
    }
  }

  /**
   * Set settings persistence handler (for automatic localStorage save/restore)
   */
  function setStoragePrefix(prefix: string) {
    storagePrefix = prefix;
  }

  function setSettingsPersistence(persistence: SettingsPersistence | null) {
    settingsPersistence = persistence;
  }

  /**
   * Get settings persistence handler
   */
  function getSettingsPersistence(): SettingsPersistence | null {
    return settingsPersistence;
  }

  /**
   * Zoom controls
   */
  function setZoom(zoom: number) {
    viewTransform.value.zoom = Math.max(0.1, Math.min(10, zoom));
  }

  function zoomIn() {
    setZoom(viewTransform.value.zoom * 1.25);
  }

  function zoomOut() {
    setZoom(viewTransform.value.zoom / 1.25);
  }

  function resetZoom() {
    if (state.value.imageSize) {
      const fitZoom = calculateFitZoom(state.value.imageSize, canvasSize.value);
      viewTransform.value = {
        ...DEFAULT_VIEW_TRANSFORM,
        zoom: fitZoom,
      };
    }
  }

  /**
   * Pan controls
   */
  function setPan(x: number, y: number) {
    viewTransform.value.panX = x;
    viewTransform.value.panY = y;
  }

  /**
   * Undo/Redo/Revert
   *
   * UI state fields (activePlugin, activeTool, selectedShapeId) are preserved
   * during undo/redo since they represent navigation state, not document state.
   */
  function undo() {
    // Preserve UI navigation state
    const { activePlugin, activeTool, selectedShapeId } = state.value;
    const result = history.undoState();
    if (result) {
      // Single assignment with UI fields merged — no intermediate state
      state.value = { ...result, activePlugin, activeTool, selectedShapeId };
    }
    return result;
  }

  function redo() {
    // Preserve UI navigation state
    const { activePlugin, activeTool, selectedShapeId } = state.value;
    const result = history.redoState();
    if (result) {
      state.value = { ...result, activePlugin, activeTool, selectedShapeId };
    }
    return result;
  }

  function revert() {
    // Preserve UI navigation state
    const { activePlugin, activeTool, selectedShapeId } = state.value;
    const result = history.revertState();
    if (result) {
      state.value = { ...result, activePlugin, activeTool, selectedShapeId };
    }
    return result;
  }

  // Computed helpers
  const isImageLoaded = computed(() => !!state.value.imageSize);
  const hasChanges = computed(() => history.currentIndex.value > 0);

  /**
   * Serialize the current project state (including history) to a JSON-serializable object
   */
  async function serialize(options: SerializeOptions = {}): Promise<SerializedProject> {
    return serializeState(state.value as EditorState, options);
  }

  async function serializeState(
    stateToSerialize: EditorState,
    options: SerializeOptions = {}
  ): Promise<SerializedProject> {
    const sourceImage = imageLoader.sourceImage.value;
    if (!sourceImage) {
      throw new Error('No image loaded');
    }

    return serializeProject(
      stateToSerialize,
      sourceImage,
      history.getEntries(),
      history.getCurrentIndex(),
      options
    );
  }

  /**
   * Load a serialized project, restoring state and history
   */
  async function loadProject(project: SerializedProject): Promise<void> {
    const deserialized = await deserializeProject(project);

    // Update the image loader with the deserialized image
    // We need to manually set the sourceImage since we're not going through load()
    imageLoader.sourceImage.value = deserialized.imageElement;
    imageLoader.imageSize.value = project.imageSize;

    // Set the editor state
    state.value = deserialized.state;

    // Calculate fit zoom
    const fitZoom = calculateFitZoom(project.imageSize, canvasSize.value);
    viewTransform.value = {
      ...DEFAULT_VIEW_TRANSFORM,
      zoom: fitZoom,
    };

    // Load history state
    history.loadHistory(deserialized.historyEntries, deserialized.historyCurrentIndex);
  }

  return {
    // State
    // shallowReadonly: prevents external .value= writes without deep-proxying
    // the state tree (readonly() would create deep Proxy wrappers for every
    // nested object — annotations, shapes, points, etc.)
    state: shallowReadonly(state),
    viewTransform,
    canvasSize,
    canvasRef,
    viewMode: readonly(viewMode),
    isAnimating: readonly(isAnimating),

    // Plugins
    plugins,
    activePlugin,

    // Image loader
    imageLoader,

    // History
    history,
    canUndo: history.canUndo,
    canRedo: history.canRedo,

    // Methods
    updateState,
    setState,
    getState,
    pushHistory,
    pushHistoryImmediate,
    getCanvas,
    getImageElement,
    createEditorContext,
    loadImage,
    setCanvasSize,
    setActivePlugin,
    setStoragePrefix,
    setSettingsPersistence,
    getSettingsPersistence,

    // Zoom/Pan
    setZoom,
    zoomIn,
    zoomOut,
    resetZoom,
    setPan,

    // History actions
    undo,
    redo,
    revert,

    // Serialization
    serialize,
    serializeState,
    loadProject,

    // Computed
    isImageLoaded,
    hasChanges,
  };
}

export type Editor = ReturnType<typeof useEditor>;
