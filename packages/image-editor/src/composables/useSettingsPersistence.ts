import { ref } from 'vue';
import type { EditorSettings, PersistedSettings, RetouchTool } from '@/types';

const STORAGE_KEY_SUFFIX = 'stimma-settings';
const SAVE_DEBOUNCE_MS = 500;

/**
 * Composable for automatic localStorage persistence of editor settings.
 * Handles loading/saving settings and remembering last selected tools.
 */
export function useSettingsPersistence(storagePrefix: string = '') {
  const storageKey = `${storagePrefix}${STORAGE_KEY_SUFFIX}`;

  // Persisted values tracked internally
  const lastAnnotateTool = ref<string | null>('sharpie');
  const lastRetouchTool = ref<RetouchTool | null>(null);
  const lastActivePlugin = ref<string | null>(null);

  // Debounce timer
  let saveTimeout: ReturnType<typeof setTimeout> | null = null;

  /**
   * Load settings from localStorage
   * Returns partial EditorSettings that can be applied to state
   */
  function loadSettings(): Partial<EditorSettings> | null {
    try {
      const stored = localStorage.getItem(storageKey);
      if (!stored) return null;

      const parsed = JSON.parse(stored) as Partial<PersistedSettings>;

      // Extract and store last tools
      if (parsed.lastAnnotateTool !== undefined) {
        lastAnnotateTool.value = parsed.lastAnnotateTool;
      }
      if (parsed.lastRetouchTool !== undefined) {
        lastRetouchTool.value = parsed.lastRetouchTool;
      }
      if (parsed.lastActivePlugin !== undefined) {
        lastActivePlugin.value = parsed.lastActivePlugin;
      }

      // Remove tool fields from returned settings (they're not part of EditorSettings)
      const { lastAnnotateTool: _at, lastRetouchTool: _rt, lastActivePlugin: _ap, ...editorSettings } = parsed;

      return editorSettings as Partial<EditorSettings>;
    } catch (err) {
      // localStorage might be disabled or quota exceeded
      console.warn('[Stimma] Failed to load settings from localStorage:', err);
      return null;
    }
  }

  /**
   * Save settings to localStorage (debounced)
   */
  function saveSettings(settings: EditorSettings): void {
    // Clear any pending save
    if (saveTimeout) {
      clearTimeout(saveTimeout);
    }

    saveTimeout = setTimeout(() => {
      saveSettingsImmediate(settings);
      saveTimeout = null;
    }, SAVE_DEBOUNCE_MS);
  }

  /**
   * Save settings immediately (no debounce)
   */
  function saveSettingsImmediate(settings: EditorSettings): void {
    try {
      const persisted: PersistedSettings = {
        ...settings,
        lastAnnotateTool: lastAnnotateTool.value,
        lastRetouchTool: lastRetouchTool.value,
        lastActivePlugin: lastActivePlugin.value,
      };

      localStorage.setItem(storageKey, JSON.stringify(persisted));
    } catch (err) {
      // localStorage might be disabled or quota exceeded
      console.warn('[Stimma] Failed to save settings to localStorage:', err);
    }
  }

  /**
   * Get the last used annotate tool (for restoration when entering annotate mode)
   */
  function getLastAnnotateTool(): string {
    return lastAnnotateTool.value ?? 'sharpie';
  }

  /**
   * Get the last used retouch tool (for restoration when entering retouch mode)
   */
  function getLastRetouchTool(): RetouchTool | null {
    return lastRetouchTool.value;
  }

  /**
   * Update the last annotate tool (called when tool changes)
   */
  function setLastAnnotateTool(tool: string | null): void {
    if (tool) {
      lastAnnotateTool.value = tool;
    }
  }

  /**
   * Update the last retouch tool (called when tool changes)
   */
  function setLastRetouchTool(tool: RetouchTool | null): void {
    lastRetouchTool.value = tool;
  }

  /**
   * Get the last active plugin (for restoration when opening a new editor)
   */
  function getLastActivePlugin(): string | null {
    return lastActivePlugin.value;
  }

  /**
   * Update the last active plugin (called when plugin changes)
   */
  function setLastActivePlugin(plugin: string | null): void {
    lastActivePlugin.value = plugin;
  }

  /**
   * Cleanup (cancel pending saves)
   */
  function cleanup(): void {
    if (saveTimeout) {
      clearTimeout(saveTimeout);
      saveTimeout = null;
    }
  }

  return {
    loadSettings,
    saveSettings,
    saveSettingsImmediate,
    getLastActivePlugin,
    getLastAnnotateTool,
    getLastRetouchTool,
    setLastActivePlugin,
    setLastAnnotateTool,
    setLastRetouchTool,
    cleanup,
  };
}

export type SettingsPersistence = ReturnType<typeof useSettingsPersistence>;
