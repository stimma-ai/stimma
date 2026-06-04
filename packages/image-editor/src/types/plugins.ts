import type { Component } from 'vue';
import type { EditorState } from './editor';
import type { Color } from './geometry';

/**
 * Retouch operations available to the retouch plugin
 */
export interface RetouchOperations {
  clearSelection: () => void;
  fillSelection: (color: Color) => void;
  clearPixels: (bgColor?: { r: number; g: number; b: number; a: number }) => void;
  featherSelection: (radius: number) => void;
  invertSelection: () => void;
  hasSelection: () => boolean;
}

/**
 * Editor context provided to plugins
 */
export interface EditorContext {
  state: EditorState;
  updateState: (partial: Partial<EditorState>) => void;
  pushHistory: (action: string) => void;
  getCanvas: () => HTMLCanvasElement | null;
  getImageElement: () => HTMLImageElement | null;
  storagePrefix: string;
  // Retouch operations (only available when retouch plugin is active)
  retouch?: RetouchOperations;
}

/**
 * Plugin state returned by setup
 */
export type PluginState = Record<string, unknown>;

/**
 * Plugin interface
 */
export interface StimmaPlugin {
  // Unique identifier
  id: string;

  // Display name for UI
  label: string;

  // Icon component or SVG string
  icon: Component | string;

  // Controls component for the plugin panel
  controls: Component;

  // Canvas overlay component (optional)
  overlay?: Component;

  // Initialize plugin state
  setup: (editor: EditorContext) => PluginState;

  // Apply plugin effects to canvas (optional)
  render?: (ctx: CanvasRenderingContext2D, state: EditorState) => void;

  // Process output image (optional)
  process?: (imageData: ImageData, state: EditorState) => ImageData;

  // Cleanup when plugin deactivates (optional)
  cleanup?: () => void;
}
