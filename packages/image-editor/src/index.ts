// Main entry point for @stimma/image-editor

// Styles
import './styles/index.css';

// Components
export { StimmaEditor } from './components';
export type { StimmaPlugin, EditorContext } from './types/plugins';

// Types
export type {
  // Geometry
  Point,
  Size,
  Rect,
  Color,
  ImageSource,

  // Editor
  EditorState,
  CropRect,
  ViewTransform,
  CropGuide,
  AspectRatioOption,
  FilterOption,
  FrameStyle,
  ExportOptions,
  LoadResult,
  ProcessResult,
  HistoryEntry,

  // Retouch
  RetouchTool,
  SelectionMode,
  DodgeBurnRange,

  // Settings
  EditorSettings,
  PersistedSettings,

  // Shapes
  Shape,
  BaseShape,
  RectangleShape,
  EllipseShape,
  LineShape,
  PathShape,
  StickerShape,
  TextShape,
  AnnotateTool,
  LineEndStyle,
  TextEffect,
  GradientDirection,
  GradientPreset,
  ShadowDirection,
} from './types';

// Shape constants
export { GRADIENT_PRESETS } from './types/shapes';

// Plugins
export { cropPlugin, finetunePlugin, filterPlugin, effectsPlugin, annotatePlugin, retouchPlugin } from './plugins';

// Utilities (for advanced usage)
export { colorToCss } from './types/geometry';
export {
  identityMatrix,
  multiplyColorMatrices,
  brightnessMatrix,
  contrastMatrix,
  saturationMatrix,
  combineAdjustments,
  applyColorMatrix,
} from './utils/colorMatrix';

// Composables (for building custom editors)
export { useEditor } from './composables/useEditor';
export { useHistory } from './composables/useHistory';
export { useImageLoader } from './composables/useImageLoader';
export { useImageWriter } from './composables/useImageWriter';
export { useSettingsPersistence } from './composables/useSettingsPersistence';
export type { SettingsPersistence } from './composables/useSettingsPersistence';

// Serialization utilities (for save/load functionality)
export {
  serializeProject,
  deserializeProject,
  serializeProjectToJson,
  deserializeProjectFromJson,
  imageToDataUrl,
  createThumbnail,
} from './utils/serialization';

export type {
  SerializedProject,
  SerializeOptions,
} from './utils/serialization';

export {
  isEditorDebugEnabled,
  nextEditorDebugSession,
  logEditorDebug,
  getRecentEditorDebugEvents,
  summarizeEditorDebugError,
  clearEditorDebugEvents,
} from './utils/editorDebug';

export {
  CHAIN_FILTER_DEFS,
  COLOR_FILTER_OPTIONS,
  getChainFilterDef,
  getChainFilterAccepts,
  getChainFilterDefaults,
  getFilterDisplayLabel,
} from './filterDefs';
export type { ChainFilterDef, ChainFilterParam } from './filterDefs';
