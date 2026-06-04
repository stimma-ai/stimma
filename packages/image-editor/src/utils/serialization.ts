import type { EditorState, HistoryEntry, Size } from '@/types';
import type { Shape, TextShape, PathShape, ShapeStyle } from '@/types/shapes';
import { TEXT_BASE_FONT_SIZE } from '@/types/shapes';

/**
 * Serialized project format for saving/loading editor state with history
 */
export interface SerializedProject {
  version: 1;
  createdAt: number;
  updatedAt: number;
  name?: string;

  // The source image as a data URL
  imageDataUrl: string;
  imageSize: Size;

  // Current editor state (without src since we have imageDataUrl)
  state: Omit<EditorState, 'src' | 'imageSize'>;

  // Full history for undo/redo (optional - omitted when includeHistory=false)
  history?: {
    entries: Array<{
      state: Omit<EditorState, 'src' | 'imageSize'>;
      timestamp: number;
      action: string;
    }>;
    currentIndex: number;
  };

  // Optional thumbnail for UI preview
  thumbnailDataUrl?: string;
}

/**
 * Options for serializing a project
 */
export interface SerializeOptions {
  name?: string;
  includeThumbnail?: boolean;
  thumbnailMaxSize?: number;
  includeHistory?: boolean;
}

/**
 * Convert an image source to a data URL
 */
export async function imageToDataUrl(
  source: HTMLImageElement | HTMLCanvasElement
): Promise<string> {
  if (source instanceof HTMLCanvasElement) {
    return source.toDataURL('image/png');
  }

  // For HTMLImageElement, draw to canvas first
  const canvas = document.createElement('canvas');
  canvas.width = source.naturalWidth || source.width;
  canvas.height = source.naturalHeight || source.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Failed to get canvas context');
  ctx.drawImage(source, 0, 0);
  return canvas.toDataURL('image/png');
}

/**
 * Create a thumbnail from an image
 */
export async function createThumbnail(
  source: HTMLImageElement | HTMLCanvasElement,
  maxSize: number = 200
): Promise<string> {
  const width = source instanceof HTMLImageElement
    ? source.naturalWidth || source.width
    : source.width;
  const height = source instanceof HTMLImageElement
    ? source.naturalHeight || source.height
    : source.height;

  // Calculate thumbnail dimensions
  const scale = Math.min(maxSize / width, maxSize / height, 1);
  const thumbWidth = Math.round(width * scale);
  const thumbHeight = Math.round(height * scale);

  const canvas = document.createElement('canvas');
  canvas.width = thumbWidth;
  canvas.height = thumbHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Failed to get canvas context');

  ctx.drawImage(source, 0, 0, thumbWidth, thumbHeight);
  return canvas.toDataURL('image/jpeg', 0.7);
}

/**
 * Convert a large data field (canvas snapshot or string) to a data URL string for serialization.
 */
function toLargeFieldDataUrl(value: HTMLCanvasElement | string | null): string | null {
  if (value instanceof HTMLCanvasElement) {
    return value.toDataURL('image/png');
  }
  return value;
}

/**
 * Strip non-serializable properties from editor state.
 * Converts canvas snapshots to data URL strings for JSON serialization.
 */
function stripStateForSerialization(
  state: EditorState
): Omit<EditorState, 'src' | 'imageSize'> {
  const { src: _src, imageSize: _imageSize, ...rest } = state;
  // Ensure canvas snapshots are converted to data URLs for serialization
  return {
    ...rest,
    retouchLayerData: toLargeFieldDataUrl(rest.retouchLayerData),
    selectionMaskData: toLargeFieldDataUrl(rest.selectionMaskData),
  } as any;
}

/**
 * Serialize a project to JSON-compatible format
 */
export async function serializeProject(
  state: EditorState,
  sourceImage: HTMLImageElement | HTMLCanvasElement,
  historyEntries: HistoryEntry[],
  historyCurrentIndex: number,
  options: SerializeOptions = {}
): Promise<SerializedProject> {
  const { name, includeThumbnail = true, thumbnailMaxSize = 200, includeHistory = true } = options;

  if (!state.imageSize) {
    throw new Error('No image loaded');
  }

  const imageDataUrl = await imageToDataUrl(sourceImage);

  const project: SerializedProject = {
    version: 1,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    name,
    imageDataUrl,
    imageSize: { ...state.imageSize },
    state: stripStateForSerialization(state),
  };

  if (includeHistory) {
    project.history = {
      entries: historyEntries.map(entry => ({
        state: stripStateForSerialization(entry.state),
        timestamp: entry.timestamp,
        action: entry.action,
      })),
      currentIndex: historyCurrentIndex,
    };
  }

  if (includeThumbnail) {
    project.thumbnailDataUrl = await createThumbnail(sourceImage, thumbnailMaxSize);
  }

  return project;
}

/**
 * Migrate a text shape from old format (with fontSize) to new vector format
 * Old format had fontSize as a pixel value
 * New format uses baseWidth/baseHeight for scalable vector text
 */
function migrateTextShape(shape: any, _imageSize: Size): TextShape {
  // If already has baseWidth/baseHeight, no migration needed
  if (shape.baseWidth !== undefined && shape.baseHeight !== undefined) {
    return shape as TextShape;
  }

  // Old format had fontSize - convert to new vector format
  const fontSize = shape.fontSize ?? 24;
  const scaleFactor = fontSize / TEXT_BASE_FONT_SIZE;

  // Calculate base dimensions from current width/height
  // If the shape was sized at fontSize, we need to find what baseWidth/baseHeight would be
  const baseWidth = (shape.width ?? 0.1) / scaleFactor;
  const baseHeight = (shape.height ?? 0.05) / scaleFactor;

  // Remove fontSize and add new properties
  const { fontSize: _removed, ...rest } = shape;

  return {
    ...rest,
    baseWidth: Math.max(baseWidth, 0.01), // Ensure minimum size
    baseHeight: Math.max(baseHeight, 0.01),
  } as TextShape;
}

/**
 * Migrate PathShape with legacy glow property to new style system
 * This is handled at render time by getEffectiveStyle, but we also migrate on load for cleanliness
 */
function migratePathShape(shape: any): PathShape {
  // If already has style with effect set, no migration needed
  if (shape.style?.effect) {
    return shape as PathShape;
  }

  // Check for legacy glow property
  if (shape.glow && shape.glow > 0) {
    const style: ShapeStyle = {
      effect: 'neon',
      glowIntensity: shape.glow,
    };
    return { ...shape, style } as PathShape;
  }

  return shape as PathShape;
}

/**
 * Migrate all shapes in an annotations array
 */
function migrateAnnotations(annotations: Shape[] | undefined, imageSize: Size): Shape[] {
  if (!annotations) return [];

  return annotations.map(shape => {
    if (shape.type === 'text') {
      return migrateTextShape(shape, imageSize);
    }
    if (shape.type === 'path') {
      return migratePathShape(shape);
    }
    return shape;
  });
}

/**
 * Migrate editor state to handle old text shape format
 */
function migrateState(state: any, imageSize: Size): any {
  if (!state.annotations) return state;

  return {
    ...state,
    annotations: migrateAnnotations(state.annotations, imageSize),
  };
}

/**
 * Deserialize a project back to editor state
 */
export async function deserializeProject(
  project: SerializedProject
): Promise<{
  state: EditorState;
  imageElement: HTMLImageElement;
  historyEntries: HistoryEntry[];
  historyCurrentIndex: number;
}> {
  // Load the image from data URL
  const imageElement = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image from project'));
    img.src = project.imageDataUrl;
  });

  // Reconstruct full editor state with migration
  const state: EditorState = migrateState({
    ...project.state,
    src: project.imageDataUrl,
    imageSize: project.imageSize,
  }, project.imageSize);

  // Reconstruct history entries with migration (handle missing history)
  const historyEntries: HistoryEntry[] = (project.history?.entries ?? []).map(entry => ({
    state: migrateState({
      ...entry.state,
      src: project.imageDataUrl,
      imageSize: project.imageSize,
    }, project.imageSize),
    timestamp: entry.timestamp,
    action: entry.action,
  }));

  return {
    state,
    imageElement,
    historyEntries,
    historyCurrentIndex: project.history?.currentIndex ?? -1,
  };
}

/**
 * Serialize project to JSON string
 */
export async function serializeProjectToJson(
  state: EditorState,
  sourceImage: HTMLImageElement | HTMLCanvasElement,
  historyEntries: HistoryEntry[],
  historyCurrentIndex: number,
  options: SerializeOptions = {}
): Promise<string> {
  const project = await serializeProject(
    state,
    sourceImage,
    historyEntries,
    historyCurrentIndex,
    options
  );
  return JSON.stringify(project);
}

/**
 * Deserialize project from JSON string
 */
export async function deserializeProjectFromJson(json: string): Promise<{
  state: EditorState;
  imageElement: HTMLImageElement;
  historyEntries: HistoryEntry[];
  historyCurrentIndex: number;
}> {
  const project: SerializedProject = JSON.parse(json);

  // Version check
  if (project.version !== 1) {
    throw new Error(`Unsupported project version: ${project.version}`);
  }

  return deserializeProject(project);
}
