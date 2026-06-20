import { ref, watch, onUnmounted, getCurrentInstance } from 'vue'
import { makeStorageKey, makeProfileKey, makeToolProfileKey } from '../utils/storageKeys'
import { getToolDefaults } from '../utils/generationDefaults'
import { getCurrentProfileId } from './useProfile'

/**
 * Generation preferences composable.
 *
 * Provides reactive containers for tool state. ToolView manages its own
 * persistence - this composable just provides the reactive refs.
 *
 * Tool schemas are the single source of truth for all parameters.
 */

// Storage key generation
function getGlobalKey(taskType: string, toolId?: number, fullToolId?: string): string {
  if (fullToolId) {
    return makeToolProfileKey(fullToolId, 'global')
  }
  if (toolId !== undefined) {
    return makeStorageKey('tool', toolId, 'global')
  }
  return makeProfileKey(taskType, 'global')
}

function getUIStateKey(taskType: string, toolId?: number, fullToolId?: string): string {
  if (fullToolId) {
    return makeToolProfileKey(fullToolId, 'ui')
  }
  if (toolId !== undefined) {
    return makeStorageKey('tool', toolId, 'ui')
  }
  return makeProfileKey(taskType, 'ui')
}

/**
 * Tool params - generic bag for whatever the tool schema defines.
 * No hardcoded fields - tool schema is the source of truth.
 */
export type ToolParams = Record<string, any>

/**
 * UI-layer defaults for fields not in tool schemas.
 */
const UI_DEFAULTS: ToolParams = {
  seed: null,
  randomizeSeed: true,
}

export interface PromptOptionSetting {
  enabled: boolean
  instructions: string
}

export interface PromptOptions {
  autoImprove: PromptOptionSetting
  varyPrompt: PromptOptionSetting
}

export const DEFAULT_PROMPT_OPTIONS: PromptOptions = {
  autoImprove: { enabled: false, instructions: '' },
  varyPrompt: { enabled: false, instructions: '' }
}

export interface GlobalPrefs {
  prompt: string
  negative_prompt: string
  folder_path: string
  inputImages: any[]
  inputVideos: any[]
  promptOptions: PromptOptions
  autoMarkerIds: number[]
  // Per-tool agent note (rides the tool + any preset saved from it): standing
  // guidance co-edited by the user and the agent.
  agentInstructions: string
  // Per-tool extended-thinking toggle — a normal tool setting (persisted,
  // scoped, rides presets). Defaults off.
  agentThinking: boolean
  // Media-batch: when true the media slot is a batch source (run once per item
  // in inputImages/inputVideos). batchField names the slot. The uniform batch
  // prep lives on the representative item (items[0]._scale/_flip/...), so there
  // is no separate prep object to persist.
  batchMode?: boolean
  batchField?: 'input_images' | 'input_videos'
}

export interface UIState {
  selectedGenerator: string
  selectedModel: string
  advancedExpanded: boolean
  aiPromptExpanded: boolean
  promptSettingsExpanded: boolean
  generateForeverMode: boolean
  generateForeverConcurrency: number
  generateForeverIdleLimit: number  // 0 = no limit, default 50
  batchSize: number  // Images queued per Run click (1-8). 1 = single generation.
  imageMode: string
  layoutMode: 'studio' | 'stage'  // 'studio' = controls primary, 'stage' = image primary
}

export interface UseGenerationPreferencesOptions {
  taskType: string
  toolId?: number
  fullToolId?: string
}

export function useGenerationPreferences(options: UseGenerationPreferencesOptions) {
  const { taskType, toolId, fullToolId } = options

  const preferencesLoaded = ref(false)
  const isLoadingPreferences = ref(false)

  // Global preferences
  const globalPrefs = ref<GlobalPrefs>({
    prompt: '',
    negative_prompt: '',
    folder_path: '',
    inputImages: [],
    inputVideos: [],
    promptOptions: { ...DEFAULT_PROMPT_OPTIONS },
    autoMarkerIds: [],
    agentInstructions: '',
    agentThinking: false,
    batchMode: false,
    batchField: 'input_images',
  })

  // UI state
  const uiState = ref<UIState>({
    selectedGenerator: '',
    selectedModel: '',
    advancedExpanded: false,
    aiPromptExpanded: true,
    promptSettingsExpanded: false,
    generateForeverMode: false,
    generateForeverConcurrency: 2,
    generateForeverIdleLimit: 50,  // Default: auto-stop after 50 images with no user changes
    batchSize: 1,
    imageMode: 'fit',
    layoutMode: 'studio'
  })

  // Tool params - generic bag, schema is source of truth
  const modelParams = ref<ToolParams>({ ...UI_DEFAULTS })

  // --- Storage Functions ---

  function loadGlobalPrefs(): void {
    if (!getCurrentProfileId()) return
    try {
      const saved = localStorage.getItem(getGlobalKey(taskType, toolId, fullToolId))
      if (saved) {
        const data = JSON.parse(saved)
        globalPrefs.value = {
          prompt: data.prompt ?? '',
          negative_prompt: data.negative_prompt ?? '',
          folder_path: data.folder_path ?? '',
          inputImages: data.inputImages ?? [],
          inputVideos: data.inputVideos ?? [],
          promptOptions: {
            autoImprove: data.promptOptions?.autoImprove ?? { enabled: false, instructions: '' },
            varyPrompt: data.promptOptions?.varyPrompt ?? { enabled: false, instructions: '' }
          },
          autoMarkerIds: data.autoMarkerIds ?? [],
          agentInstructions: data.agentInstructions ?? '',
          agentThinking: data.agentThinking ?? false,
          batchMode: data.batchMode ?? false,
          batchField: data.batchField ?? 'input_images',
        }
      }
    } catch (err) {
      console.error(`Failed to load global prefs for ${taskType}:`, err)
    }
  }

  function saveGlobalPrefs(): void {
    if (!preferencesLoaded.value || isLoadingPreferences.value) return
    if (!getCurrentProfileId()) return
    try {
      // Strip large data URLs from inputImages before saving — paint layers
      // are persisted separately via dedicated storage in ToolView
      const cleanedPrefs = {
        ...globalPrefs.value,
        inputImages: globalPrefs.value.inputImages.map((img: any) => {
          if (!img._paintLayerDataUrl) return img
          const { _paintLayerDataUrl, ...rest } = img
          return rest
        })
      }
      localStorage.setItem(getGlobalKey(taskType, toolId, fullToolId), JSON.stringify(cleanedPrefs))
    } catch (err) {
      console.error(`Failed to save global prefs for ${taskType}:`, err)
    }
  }

  function loadUIState(): void {
    if (!getCurrentProfileId()) return
    try {
      const saved = localStorage.getItem(getUIStateKey(taskType, toolId, fullToolId))
      if (saved) {
        const data = JSON.parse(saved)
        uiState.value = {
          selectedGenerator: data.selectedGenerator ?? '',
          selectedModel: data.selectedModel ?? '',
          advancedExpanded: data.advancedExpanded ?? false,
          aiPromptExpanded: data.aiPromptExpanded ?? true,
          promptSettingsExpanded: data.promptSettingsExpanded ?? false,
          // Never restore active forever mode across reloads.
          generateForeverMode: false,
          generateForeverConcurrency: data.generateForeverConcurrency ?? 2,
          generateForeverIdleLimit: data.generateForeverIdleLimit ?? 50,
          batchSize: Math.min(8, Math.max(1, data.batchSize ?? 1)),
          imageMode: data.imageMode ?? 'fit',
          layoutMode: data.layoutMode === 'stage' ? 'stage' : 'studio'
        }
      }
    } catch (err) {
      console.error(`Failed to load UI state for ${taskType}:`, err)
    }
  }

  function saveUIState(): void {
    if (!preferencesLoaded.value || isLoadingPreferences.value) return
    if (!getCurrentProfileId()) return
    try {
      // Never persist active forever mode so reloads always start disabled.
      const persistedUIState = {
        ...uiState.value,
        generateForeverMode: false
      }
      localStorage.setItem(getUIStateKey(taskType, toolId, fullToolId), JSON.stringify(persistedUIState))
    } catch (err) {
      console.error(`Failed to save UI state for ${taskType}:`, err)
    }
  }

  /**
   * Load tool params. Uses tool schema defaults merged with UI defaults.
   * No hardcoded fields - just merges whatever the schema provides.
   */
  function loadModelParams(_generator: string, _model: string, toolOrSchema?: any, _modelObj?: any): void {
    // Get defaults from tool schema
    let toolDefaults: ToolParams = {}
    if (toolOrSchema?.parameter_schema) {
      toolDefaults = getToolDefaults(toolOrSchema.parameter_schema)
    } else if (toolOrSchema) {
      toolDefaults = getToolDefaults(toolOrSchema)
    }

    // Merge: UI defaults + tool schema defaults
    const defaults = { ...UI_DEFAULTS, ...toolDefaults }
    modelParams.value = { ...defaults }
  }

  // Note: saveModelParams is a no-op - ToolView handles its own persistence
  function saveModelParams(): void {}

  // --- Public API ---

  function init(): void {
    isLoadingPreferences.value = true
    loadGlobalPrefs()
    loadUIState()
    isLoadingPreferences.value = false
    preferencesLoaded.value = true
  }

  function onGeneratorChanged(generator: string, defaultModel?: string, schema?: any, modelObj?: any): void {
    uiState.value.selectedGenerator = generator
    if (defaultModel) {
      uiState.value.selectedModel = defaultModel
      loadModelParams(generator, defaultModel, schema, modelObj)
    }
    saveUIState()
  }

  function onModelChanged(model: string, schema?: any, modelObj?: any): void {
    uiState.value.selectedModel = model
    loadModelParams(uiState.value.selectedGenerator || '_tool_', model, schema, modelObj)
    saveUIState()
  }

  /**
   * Revert to tool schema defaults.
   */
  function revertToDefaults(toolOrSchema?: any): void {
    let toolDefaults: ToolParams = {}
    if (toolOrSchema?.parameter_schema) {
      toolDefaults = getToolDefaults(toolOrSchema.parameter_schema)
    } else if (toolOrSchema) {
      toolDefaults = getToolDefaults(toolOrSchema)
    }

    const defaults = { ...UI_DEFAULTS, ...toolDefaults }
    modelParams.value = {
      ...defaults,
      seed: Math.floor(Math.random() * 4294967296)
    }
  }

  function revertToDefaultsIncludingLoras(toolOrSchema?: any): void {
    revertToDefaults(toolOrSchema)
  }

  /** @deprecated */
  function getDefaults(): ToolParams {
    return { ...UI_DEFAULTS }
  }

  // Debounced saving for globalPrefs and uiState
  let globalSaveTimeout: ReturnType<typeof setTimeout> | null = null
  let uiSaveTimeout: ReturnType<typeof setTimeout> | null = null

  function debouncedSaveGlobal(): void {
    if (globalSaveTimeout) clearTimeout(globalSaveTimeout)
    globalSaveTimeout = setTimeout(saveGlobalPrefs, 500)
  }

  function debouncedSaveUI(): void {
    if (uiSaveTimeout) clearTimeout(uiSaveTimeout)
    uiSaveTimeout = setTimeout(saveUIState, 500)
  }

  watch(globalPrefs, debouncedSaveGlobal, { deep: true })
  watch(uiState, debouncedSaveUI, { deep: true })

  // Flush any pending debounced saves immediately (used before profile switch)
  function flushPendingSaves(): void {
    if (globalSaveTimeout) {
      clearTimeout(globalSaveTimeout)
      globalSaveTimeout = null
      saveGlobalPrefs()
    }
    if (uiSaveTimeout) {
      clearTimeout(uiSaveTimeout)
      uiSaveTimeout = null
      saveUIState()
    }
  }

  // Handle profile-will-change - flush pending saves to OLD profile's storage
  function handleProfileWillChange(): void {
    flushPendingSaves()
  }

  // Handle profile-changed - reload from new profile's storage
  function handleProfileChanged(): void {
    // Reset loaded state and reload from new profile's storage keys
    preferencesLoaded.value = false
    isLoadingPreferences.value = true

    // Cancel any pending saves (we already flushed in will-change)
    if (globalSaveTimeout) {
      clearTimeout(globalSaveTimeout)
      globalSaveTimeout = null
    }
    if (uiSaveTimeout) {
      clearTimeout(uiSaveTimeout)
      uiSaveTimeout = null
    }

    // Reset to defaults first
    globalPrefs.value = {
      prompt: '',
      negative_prompt: '',
      folder_path: '',
      inputImages: [],
      inputVideos: [],
      promptOptions: { ...DEFAULT_PROMPT_OPTIONS },
      autoMarkerIds: [],
      agentInstructions: '',
      agentThinking: false,
      batchMode: false,
      batchField: 'input_images',
    }
    uiState.value = {
      selectedGenerator: '',
      selectedModel: '',
      advancedExpanded: false,
      aiPromptExpanded: true,
      promptSettingsExpanded: false,
      generateForeverMode: false,
      generateForeverConcurrency: 2,
      generateForeverIdleLimit: 50,
      batchSize: 1,
      imageMode: 'fit',
      layoutMode: 'studio'
    }
    modelParams.value = { ...UI_DEFAULTS }

    // Reload from new profile's storage
    loadGlobalPrefs()
    loadUIState()
    isLoadingPreferences.value = false
    preferencesLoaded.value = true
  }

  // Set up profile and account event listeners with cleanup
  if (typeof window !== 'undefined') {
    window.addEventListener('profile-will-change', handleProfileWillChange)
    window.addEventListener('profile-changed', handleProfileChanged)

    // Clean up listeners when component unmounts (if used in component context)
    const instance = getCurrentInstance()
    if (instance) {
      onUnmounted(() => {
        window.removeEventListener('profile-will-change', handleProfileWillChange)
        window.removeEventListener('profile-changed', handleProfileChanged)
      })
    }
  }

  return {
    globalPrefs,
    modelParams,
    uiState,
    preferencesLoaded,
    isLoadingPreferences,
    init,
    onGeneratorChanged,
    onModelChanged,
    revertToDefaults,
    revertToDefaultsIncludingLoras,
    getDefaults,
    saveGlobalPrefs,
    saveModelParams,
    saveUIState,
    loadUIState,
    loadModelParams
  }
}

// Legacy export for backwards compatibility
export type ModelDefaults = ToolParams
