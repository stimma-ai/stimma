import type {
  EditorState,
  LoadProgress,
  LoadResult,
  ProcessProgress,
  ProcessResult,
} from './editor';

/**
 * Editor component events
 */
export interface StimmaEditorEmits {
  // Loading
  (e: 'load-start'): void;
  (e: 'load-progress', progress: LoadProgress): void;
  (e: 'load', result: LoadResult): void;
  (e: 'load-error', error: Error): void;

  // Processing
  (e: 'process-start'): void;
  (e: 'process-progress', progress: ProcessProgress): void;
  (e: 'process', result: ProcessResult): void;
  (e: 'process-error', error: Error): void;

  // State changes
  (e: 'update', state: EditorState): void;
  (e: 'update:imageState', state: EditorState): void;

  // UI events
  (e: 'close'): void;
  (e: 'revert'): void;
}
