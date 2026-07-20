import { ref, computed, watch, nextTick, type Ref, type ComputedRef, type WatchStopHandle } from 'vue'
import { usePresetsApi } from './usePresetsApi'
import { getToolDefaults } from '../utils/generationDefaults'
import { getCurrentProfileId } from './useProfile'
import { makeToolProfileKey } from '../utils/storageKeys'
import { emptyChain, normalizeChain, type PostProcessingChain } from '../utils/postProcessingChain'
import { AUDIO_TASK_TYPES } from '../utils/taskTypeIcons'

// Tool state type (parameters, loras, etc.)
export type ToolState = Record<string, any>

function findLegacyToolKey(fullToolId: string, part: string): string | null {
  const safeToolId = fullToolId.replace(/:/g, '_')
  const suffix = `_tool_${safeToolId}_${part}`
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key) continue
    if (key.startsWith('stimma') && key.endsWith(suffix)) {
      return key
    }
  }
  return null
}

// Ephemeral keys that shouldn't be part of saved state. agentThinking is a
// legacy key — the per-tool thinking toggle was removed (2026-07, the cloud
// tiers pin reasoning server-side); old saved states/presets may still carry
// it, so it must be ignored on apply and in the modified comparison.
const EPHEMERAL_STATE_KEYS = new Set(['seed', 'randomizeSeed', 'selected_loras', 'folder_path', 'agentThinking'])

export interface UseToolStateOptions {
  fullToolId: string       // The actual tool ID (for API calls)
  scopedToolId?: string    // Project-scoped ID for storage keys (defaults to fullToolId)
  tool: Ref<any>
  globalPrefs: Ref<any>
  modelParams: Ref<any>
  toolLoras: Ref<Array<{ lora: string; weight: number; enabled: boolean }>>
  toolChain: Ref<PostProcessingChain>
  uiState: Ref<any>
  saveToolState: (toolId: string, state: ToolState) => Promise<void>
}

export interface UseToolStateReturn {
  // State
  activePreset: Ref<any | null>
  baseState: Ref<ToolState>
  collapsedGroups: Ref<Record<string, boolean>>

  // Computed
  hasActivePreset: ComputedRef<boolean>
  selectedPresetId: ComputedRef<number | null>
  isModified: ComputedRef<boolean>

  // Methods
  buildToolState: () => ToolState
  applyToolState: (state: ToolState) => void
  saveStateToLocalStorage: () => void
  loadStateFromLocalStorage: () => ToolState | null
  clearLocalStorageState: () => void
  debouncedSaveState: () => void

  // Collapsed groups
  getGroupCollapsed: (groupLabel: string | null) => boolean
  toggleGroupCollapsed: (groupLabel: string | null) => void
  loadCollapsedGroups: () => void

  // AI prompt expanded
  loadAIPromptExpanded: () => boolean
  saveAIPromptExpanded: (expanded: boolean) => void

  // Preset handlers
  loadActivePresetId: () => number | null
  saveActivePresetId: (presetId: number | null) => void
  handlePresetSelect: (preset: any) => void
  handlePresetSaved: (preset: any) => void
  clearActivePreset: () => void
  revertToBaseState: () => void
  saveToActivePreset: () => Promise<void>
  saveAsToolDefaults: () => Promise<void>

  // Initialization
  initializeState: (savedPresetId: number | null) => Promise<void>
  startWatchingChanges: () => void
  stopWatching: () => void
  flushPendingSaves: () => void
}

export function useToolState(options: UseToolStateOptions): UseToolStateReturn {
  const { fullToolId, tool, globalPrefs, modelParams, toolLoras, toolChain, uiState, saveToolState } = options
  const storageToolId = options.scopedToolId || fullToolId

  // Preset state
  const activePreset = ref<any | null>(null)
  const baseState = ref<ToolState>({})

  // Collapsed state for collapsible groups
  const collapsedGroups = ref<Record<string, boolean>>({})

  // Computed properties
  const hasActivePreset = computed(() => activePreset.value !== null)
  const selectedPresetId = computed(() => activePreset.value?.id ?? null)

  // Storage key helpers (use storageToolId for project-scoped isolation)
  function getToolStateKey() {
    return makeToolProfileKey(storageToolId, 'state')
  }

  function getActivePresetKey() {
    return makeToolProfileKey(storageToolId, 'active_preset')
  }

  function getCollapsedGroupsKey() {
    return makeToolProfileKey(storageToolId, 'collapsed_groups')
  }

  function getAIPromptExpandedKey() {
    return makeToolProfileKey(storageToolId, 'ai_prompt_expanded')
  }

  // Build the complete tool state as a single blob
  function buildToolState(): ToolState {
    const state: ToolState = {}

    // Include ALL model params except ephemeral ones
    for (const [key, value] of Object.entries(modelParams.value)) {
      if (!EPHEMERAL_STATE_KEYS.has(key)) {
        state[key] = value
      }
    }

    // Include global prefs
    state.prompt = globalPrefs.value.prompt || ''
    // Strip large data URLs from inputImages — paint layers are persisted
    // separately via dedicated storage in ToolView
    state.inputImages = (globalPrefs.value.inputImages || []).map((img: any) => {
      if (!img._paintLayerDataUrl) return img
      const { _paintLayerDataUrl, ...rest } = img
      return rest
    })
    state.inputVideos = globalPrefs.value.inputVideos || []
    state.inputAudios = globalPrefs.value.inputAudios || []
    state.promptOptions = globalPrefs.value.promptOptions || {
      autoImprove: { enabled: false, instructions: '' },
      varyPrompt: { enabled: false, instructions: '' }
    }
    state.autoMarkerIds = globalPrefs.value.autoMarkerIds || []

    // Per-tool agent Instructions ride the state blob, so they travel with the
    // tool's working state AND any preset saved from it.
    state.agentInstructions = globalPrefs.value.agentInstructions || ''

    // Media-batch slot state rides the tool's working state so it survives reload
    // (and presets) — otherwise the items restore but the slot reverts to N refs.
    state.batchMode = globalPrefs.value.batchMode ?? false
    state.batchField = globalPrefs.value.batchField ?? 'input_images'

    // Include ALL loras with their enabled state
    state.loras = toolLoras.value.map(l => ({
      lora: l.lora,
      weight: l.weight,
      enabled: l.enabled
    }))

    // Post-processing chain rides the state blob like the LoRA pool — full
    // chain including disabled steps (the editing surface; lineage separately
    // records only the steps that ran).
    state.postProcessingChain = {
      enabled: toolChain.value.enabled,
      steps: toolChain.value.steps.map(s => ({ ...s, settings: { ...s.settings } }))
    }

    return state
  }

  // Apply a tool state blob to the UI
  function applyToolState(state: ToolState) {
    // Apply global prefs
    globalPrefs.value.prompt = state.prompt ?? ''
    globalPrefs.value.inputImages = state.inputImages ?? []
    globalPrefs.value.inputVideos = state.inputVideos ?? []
    globalPrefs.value.inputAudios = state.inputAudios ?? []
    globalPrefs.value.promptOptions = state.promptOptions ?? {
      autoImprove: { enabled: false, instructions: '' },
      varyPrompt: { enabled: false, instructions: '' }
    }
    globalPrefs.value.autoMarkerIds = state.autoMarkerIds ?? []
    globalPrefs.value.agentInstructions = state.agentInstructions ?? ''
    globalPrefs.value.batchMode = state.batchMode ?? false
    globalPrefs.value.batchField = state.batchField ?? 'input_images'

    // Apply ALL model params from state (except ephemeral)
    for (const [key, value] of Object.entries(state)) {
      if (!EPHEMERAL_STATE_KEYS.has(key) && value != null) {
        ;(modelParams.value as any)[key] = value
      }
    }

    // Apply loras (including disabled ones)
    toolLoras.value = (state.loras ?? []).map(l => ({
      lora: l.lora,
      weight: l.weight,
      enabled: l.enabled ?? true
    }))

    // Apply post-processing chain (including disabled steps)
    toolChain.value = state.postProcessingChain
      ? normalizeChain(state.postProcessingChain)
      : emptyChain()
  }

  // Save current state to localStorage (working copy)
  function saveStateToLocalStorage() {
    if (!tool.value) return
    if (!getCurrentProfileId()) return  // profile not yet set (e.g. browser reload)
    const state = buildToolState()
    localStorage.setItem(getToolStateKey(), JSON.stringify(state))
  }

  // Load state from localStorage (returns null if not present)
  function loadStateFromLocalStorage(): ToolState | null {
    if (!tool.value) return null
    if (!getCurrentProfileId()) return null  // profile not yet set
    let saved = localStorage.getItem(getToolStateKey())
    // Legacy-key rescue predates scoped ids. Never apply it to instance-scoped
    // state: a fresh instance must start from tool defaults, not resurrect
    // pre-instance leftovers (the tab migration already moved live state).
    if (!saved && !storageToolId.includes('__i_')) {
      const legacyKey = findLegacyToolKey(fullToolId, 'state')
      if (legacyKey) {
        saved = localStorage.getItem(legacyKey)
        if (saved) {
          localStorage.setItem(getToolStateKey(), saved)
        }
      }
    }
    if (!saved) return null
    try {
      return JSON.parse(saved)
    } catch (e) {
      console.error('Failed to parse saved tool state:', e)
      return null
    }
  }

  // Clear localStorage working copy
  function clearLocalStorageState() {
    if (!tool.value) return
    localStorage.removeItem(getToolStateKey())
  }

  // Debounced save to localStorage
  let stateSaveTimeout: ReturnType<typeof setTimeout> | null = null
  function debouncedSaveState() {
    if (stateSaveTimeout) clearTimeout(stateSaveTimeout)
    stateSaveTimeout = setTimeout(saveStateToLocalStorage, 500)
  }

  // Check if current state differs from base state
  const isModified = computed(() => {
    if (!tool.value) return false
    if (Object.keys(baseState.value).length === 0) return false

    const currentState = buildToolState()
    const base = baseState.value

    const allKeys = new Set([...Object.keys(base), ...Object.keys(currentState)])

    for (const key of allKeys) {
      if (EPHEMERAL_STATE_KEYS.has(key)) continue
      if (key === 'inputImages' || key === 'inputVideos' || key === 'inputAudios') continue

      // agentInstructions defaults to '' but older states omit the key entirely;
      // treat absent and empty as equal so loading a pre-feature preset doesn't
      // read as modified the instant it loads.
      if (key === 'agentInstructions' || key === 'agentMemory') {
        if ((currentState[key] || '') !== (base[key] || '')) return true
        continue
      }

      // Batch slot state: absent in pre-feature states; treat absent as the
      // default so loading an older state/preset doesn't read as modified.
      if (key === 'batchMode') {
        if ((currentState[key] ?? false) !== (base[key] ?? false)) return true
        continue
      }
      if (key === 'batchField') {
        if ((currentState[key] ?? 'input_images') !== (base[key] ?? 'input_images')) return true
        continue
      }
      const currentVal = JSON.stringify(currentState[key])
      const baseVal = JSON.stringify(base[key])
      if (currentVal !== baseVal) {
        return true
      }
    }

    return false
  })

  // Collapsed groups management
  function loadCollapsedGroups() {
    const stored = localStorage.getItem(getCollapsedGroupsKey())
    if (stored) {
      try {
        collapsedGroups.value = JSON.parse(stored)
      } catch {
        collapsedGroups.value = {}
      }
    }
  }

  function saveCollapsedGroups() {
    localStorage.setItem(getCollapsedGroupsKey(), JSON.stringify(collapsedGroups.value))
  }

  function getGroupCollapsed(groupLabel: string | null): boolean {
    if (!groupLabel) return false
    if (groupLabel in collapsedGroups.value) {
      return collapsedGroups.value[groupLabel]
    }
    return true // collapsed by default for collapsible groups
  }

  function toggleGroupCollapsed(groupLabel: string | null) {
    if (!groupLabel) return
    const current = getGroupCollapsed(groupLabel)
    collapsedGroups.value[groupLabel] = !current
    saveCollapsedGroups()
  }

  // AI prompt expanded state
  function loadAIPromptExpanded(): boolean {
    const saved = localStorage.getItem(getAIPromptExpandedKey())
    // Default to expanded if no saved preference
    return saved === null ? true : saved === 'true'
  }

  function saveAIPromptExpanded(expanded: boolean) {
    localStorage.setItem(getAIPromptExpandedKey(), String(expanded))
  }

  // Preset management
  function loadActivePresetId(): number | null {
    const stored = localStorage.getItem(getActivePresetKey())
    return stored ? parseInt(stored, 10) : null
  }

  function saveActivePresetId(presetId: number | null) {
    if (presetId === null) {
      localStorage.removeItem(getActivePresetKey())
    } else {
      localStorage.setItem(getActivePresetKey(), String(presetId))
    }
  }

  // Apply a state blob and take the baseline from what the UI SETTLES on, not
  // from the blob itself. Applying is lossy in both directions: params the blob
  // omits keep their old value, and post-apply watchers (x-constraint
  // force_value, prompt-option normalization) rewrite params right after. A
  // baseline captured from the blob therefore disagrees with buildToolState()
  // on those keys forever — the tool reads as modified the instant it's reset
  // or a preset is loaded, and Revert can't clear it because it re-applies the
  // same blob and lands in the same place.
  function applyStateAndRebaseline(state: ToolState) {
    applyToolState(state)
    baseState.value = { ...state }
    nextTick(() => {
      baseState.value = buildToolState()
    })
  }

  function handlePresetSelect(preset: any) {
    activePreset.value = preset
    saveActivePresetId(preset.id)

    if (preset.state) {
      applyStateAndRebaseline(preset.state)
    }

    clearLocalStorageState()
  }

  function handlePresetSaved(preset: any) {
    activePreset.value = preset
    saveActivePresetId(preset.id)
    baseState.value = { ...preset.state }
  }

  function clearActivePreset() {
    activePreset.value = null
    saveActivePresetId(null)

    const schemaDefaults = tool.value
      ? getToolDefaults(tool.value.parameter_schema)
      : {}

    // Keep the existing LoRA pool entries and weights, but deselect all.
    const preservedLoras = (toolLoras.value || []).map(l => ({
      lora: l.lora,
      weight: l.weight,
      enabled: false
    }))

    const defaultState: ToolState = {
      ...schemaDefaults,
      prompt: '',
      negative_prompt: schemaDefaults.negativePrompt ?? '',
      inputImages: [],
      inputVideos: [],
      inputAudios: [],
      promptOptions: {
        autoImprove: { enabled: false, instructions: '' },
        varyPrompt: { enabled: false, instructions: '' }
      },
      autoMarkerIds: [],
      // Per-tool Instructions are durable scaffolding for the tool (like the
      // LoRA pool above) — a generation reset keeps them.
      agentInstructions: globalPrefs.value.agentInstructions ?? '',
      loras: preservedLoras,
      // Keep the chain's steps (workflow scaffolding, like the LoRA pool) but
      // turn post-processing off.
      postProcessingChain: {
        enabled: false,
        steps: toolChain.value.steps.map(s => ({ ...s, settings: { ...s.settings } }))
      }
    }

    // A reset must clear params the schema has no default for — applyToolState
    // only writes the keys it's given, so anything the user set that isn't in
    // defaultState would otherwise survive a "Reset to Defaults".
    for (const key of Object.keys(modelParams.value)) {
      if (!(key in defaultState) && !EPHEMERAL_STATE_KEYS.has(key)) {
        delete (modelParams.value as any)[key]
      }
    }

    applyStateAndRebaseline(defaultState)

    clearLocalStorageState()
  }

  function revertToBaseState() {
    applyStateAndRebaseline(baseState.value)
    clearLocalStorageState()
  }

  async function saveToActivePreset() {
    if (!activePreset.value) return

    const state = buildToolState()

    try {
      const { updatePreset } = usePresetsApi()
      const updatedPreset = await updatePreset(activePreset.value.id, { state })

      activePreset.value = updatedPreset
      baseState.value = { ...state }

      clearLocalStorageState()
    } catch (err) {
      console.error('Failed to save preset:', err)
    }
  }

  async function saveAsToolDefaults() {
    if (!tool.value) return

    const state = buildToolState()

    try {
      await saveToolState(tool.value.full_tool_id, state)
      tool.value.state = state
      baseState.value = { ...state }
      clearLocalStorageState()
    } catch (err) {
      console.error('Failed to save tool settings:', err)
    }
  }

  // Initialize state from preset or tool defaults
  async function initializeState(savedPresetId: number | null) {
    // Seed the task-type-aware Enhance Prompt default before any saved state
    // is applied below. Brand-new tools (no preset, no localStorage, no
    // backend-saved state) never hit an applyToolState() call in this
    // function, so this seed is what actually sticks for them; a real saved
    // value (preset/localStorage/tool state) overrides it further down.
    globalPrefs.value.promptOptions = {
      ...globalPrefs.value.promptOptions,
      autoImprove: {
        enabled: !(AUDIO_TASK_TYPES as readonly string[]).includes(tool.value?.task_type || ''),
        instructions: globalPrefs.value.promptOptions?.autoImprove?.instructions ?? '',
      },
    }

    if (savedPresetId) {
      try {
        const { getPreset } = usePresetsApi()
        const preset = await getPreset(savedPresetId)
        activePreset.value = preset
        baseState.value = { ...preset.state }

        const localState = loadStateFromLocalStorage()
        if (localState) {
          applyToolState(localState)
        } else {
          applyToolState(preset.state)
        }
      } catch (err) {
        console.warn('Saved preset not found, clearing:', err)
        saveActivePresetId(null)
        activePreset.value = null

        baseState.value = { ...tool.value.state }
        const localState = loadStateFromLocalStorage()
        if (localState) {
          applyToolState(localState)
        } else if (tool.value.state && Object.keys(tool.value.state).length > 0) {
          applyToolState(tool.value.state)
        }
      }
    } else {
      baseState.value = { ...tool.value.state }

      const localState = loadStateFromLocalStorage()
      if (localState) {
        applyToolState(localState)
      } else if (tool.value.state && Object.keys(tool.value.state).length > 0) {
        applyToolState(tool.value.state)
      }
    }
  }

  // Track active watchers for cleanup
  let watchStopHandles: WatchStopHandle[] = []

  // Start watching for changes to save to localStorage
  function startWatchingChanges() {
    // Stop any existing watchers first to prevent stacking (e.g. on profile switch)
    stopWatching()
    nextTick(() => {
      watchStopHandles.push(
        watch([globalPrefs, modelParams, toolLoras, toolChain, uiState], debouncedSaveState, { deep: true })
      )

      watchStopHandles.push(
        watch(() => uiState.value.aiPromptExpanded, (expanded) => {
          saveAIPromptExpanded(expanded)
        })
      )
    })
  }

  // Stop all active watchers and clear pending debounce
  function stopWatching() {
    for (const stop of watchStopHandles) {
      stop()
    }
    watchStopHandles = []
    if (stateSaveTimeout) {
      clearTimeout(stateSaveTimeout)
      stateSaveTimeout = null
    }
  }

  // Flush any pending debounced save immediately
  function flushPendingSaves() {
    if (stateSaveTimeout) {
      clearTimeout(stateSaveTimeout)
      stateSaveTimeout = null
      saveStateToLocalStorage()
    }
  }

  return {
    // State
    activePreset,
    baseState,
    collapsedGroups,

    // Computed
    hasActivePreset,
    selectedPresetId,
    isModified,

    // Methods
    buildToolState,
    applyToolState,
    saveStateToLocalStorage,
    loadStateFromLocalStorage,
    clearLocalStorageState,
    debouncedSaveState,

    // Collapsed groups
    getGroupCollapsed,
    toggleGroupCollapsed,
    loadCollapsedGroups,

    // AI prompt expanded
    loadAIPromptExpanded,
    saveAIPromptExpanded,

    // Preset handlers
    loadActivePresetId,
    saveActivePresetId,
    handlePresetSelect,
    handlePresetSaved,
    clearActivePreset,
    revertToBaseState,
    saveToActivePreset,
    saveAsToolDefaults,

    // Initialization
    initializeState,
    startWatchingChanges,
    stopWatching,
    flushPendingSaves,
  }
}
