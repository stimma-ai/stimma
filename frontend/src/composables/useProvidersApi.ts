/**
 * Providers API composable
 * Handles all API calls for provider and tool management (Toolsv3)
 *
 * Providers are sources of tools (built-in, JSON-RPC external).
 * Tools are identified by full tool ID: provider_id:tool_id
 */
import axios from 'axios'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getApiBase } from '../apiConfig'
import { useWebSocket } from './useWebSocket'

function getToolsAPIBase() {
  return `${getApiBase()}/tools`
}

/**
 * Provider status
 */
export type ProviderStatus = 'connected' | 'disconnected' | 'connecting' | 'error'

/**
 * Tool availability status
 * - available: Provider is connected and tool is usable
 * - disconnected: Provider is configured but not connected
 * - unconfigured: Provider was removed from config
 */
export type ToolAvailability = 'available' | 'disconnected' | 'unconfigured'

/**
 * Provider info from the API
 */
export interface Provider {
  provider_id: string
  provider_name: string  // Human-readable display name
  provider_type: string  // "builtin", "jsonrpc"
  status: ProviderStatus
  tool_count: number
  max_concurrent: number
}

/**
 * Tool descriptor from provider
 */
export interface ProviderTool {
  full_tool_id: string  // "provider_id:tool_id"
  tool_id: string
  name: string
  subtitle?: string  // Short description for UI
  task_type: string  // Primary task type (backward compat)
  task_types: string[]  // All task types this tool supports
  provider_id: string
  provider_name: string
  parameter_schema: Record<string, any>
  output_schema: Record<string, any>
  metadata: Record<string, any>
  availability: ToolAvailability  // "available", "disconnected", "unconfigured"
}

/**
 * Grouped tools by provider
 */
export interface ProviderWithTools {
  provider: Provider
  tools: ProviderTool[]
}

// Reactive state for caching
const providersCache = ref<Provider[]>([])
const toolsCache = ref<ProviderTool[]>([])
const lastFetchTime = ref<number>(0)
const CACHE_TTL = 30000 // 30 seconds

// Module-level cache clearing function (used by event handlers)
function clearToolsCache() {
  providersCache.value = []
  toolsCache.value = []
  lastFetchTime.value = 0
}

// Listen for tools-changed browser event (dispatched by useWebSocket)
window.addEventListener('tools-changed', () => {
  console.log('[ProvidersApi] Received tools-changed, clearing cache')
  clearToolsCache()
})

// Clear tools cache on profile change (different profiles may have different tools)
window.addEventListener('profile-changed', () => {
  console.log('[ProvidersApi] Profile changed, clearing tools cache')
  clearToolsCache()
})

export function useProvidersApi() {
  /**
   * List all registered providers
   */
  async function listProviders(): Promise<Provider[]> {
    const response = await axios.get(`${getToolsAPIBase()}/providers`)
    providersCache.value = response.data
    return response.data
  }

  /**
   * Get a specific provider by ID
   */
  async function getProvider(providerId: string): Promise<Provider> {
    const response = await axios.get(`${getToolsAPIBase()}/providers/${providerId}`)
    return response.data
  }

  /**
   * List all tools from all providers
   */
  async function listAllTools(): Promise<ProviderTool[]> {
    const response = await axios.get(`${getToolsAPIBase()}/providers/tools`)
    toolsCache.value = response.data
    lastFetchTime.value = Date.now()
    return response.data
  }

  /**
   * Fetch providers and tools together, with caching
   */
  async function fetchProvidersAndTools(forceRefresh = false): Promise<{
    providers: Provider[]
    tools: ProviderTool[]
  }> {
    const now = Date.now()
    if (!forceRefresh && lastFetchTime.value > 0 && now - lastFetchTime.value < CACHE_TTL) {
      return {
        providers: providersCache.value,
        tools: toolsCache.value,
      }
    }

    const [providers, tools] = await Promise.all([
      listProviders(),
      listAllTools(),
    ])

    return { providers, tools }
  }

  /**
   * Get tools grouped by provider
   */
  async function getToolsGroupedByProvider(): Promise<ProviderWithTools[]> {
    const { providers, tools } = await fetchProvidersAndTools()

    return providers.map(provider => ({
      provider,
      tools: tools.filter(t => t.provider_id === provider.provider_id),
    }))
  }

  /**
   * Get tools filtered by task type.
   * Matches tools where ANY of their task_types includes the given type.
   */
  async function getToolsByTaskType(taskType: string): Promise<ProviderTool[]> {
    const { tools } = await fetchProvidersAndTools()
    return tools.filter(t => {
      const toolTaskTypes = t.task_types?.length ? t.task_types : [t.task_type]
      return toolTaskTypes.includes(taskType)
    })
  }

  /**
   * Get a specific tool by full tool ID (from cache)
   */
  async function getTool(fullToolId: string): Promise<ProviderTool | null> {
    const { tools } = await fetchProvidersAndTools()
    return tools.find(t => t.full_tool_id === fullToolId) || null
  }

  /**
   * Get a specific provider tool by full ID (fresh from API)
   */
  async function getProviderTool(fullToolId: string): Promise<ProviderTool> {
    const response = await axios.get(`${getToolsAPIBase()}/provider-tool/${encodeURIComponent(fullToolId)}`)
    return response.data
  }

  /**
   * Check if a provider is available (connected)
   */
  function isProviderAvailable(providerId: string): boolean {
    const provider = providersCache.value.find(p => p.provider_id === providerId)
    return provider?.status === 'connected'
  }

  /**
   * Get available task types from all providers.
   * Collects ALL task_types from tools that declare multiple types.
   */
  async function getAvailableTaskTypes(): Promise<string[]> {
    const { tools } = await fetchProvidersAndTools()
    const taskTypes = new Set<string>()
    for (const tool of tools) {
      const toolTaskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
      for (const tt of toolTaskTypes) {
        taskTypes.add(tt)
      }
    }
    return Array.from(taskTypes).sort()
  }

  /**
   * Clear the cache to force fresh data on next fetch
   */
  function clearCache() {
    providersCache.value = []
    toolsCache.value = []
    lastFetchTime.value = 0
  }

  /**
   * Upload a file to a tool's parameter (e.g., LoRA upload).
   *
   * @param fullToolId - Full tool ID (provider_id:tool_id)
   * @param parameter - Parameter name (e.g., "loras")
   * @param file - File to upload
   * @param onProgress - Optional progress callback (0-100)
   * @returns Upload result with installed_path
   */
  async function uploadToTool(
    fullToolId: string,
    parameter: string,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<{ success: boolean; installed_path?: string; lora_id?: string; error?: string }> {
    // Two-phase upload:
    //   1. /upload-prepare → backend returns the URL to PUT bytes to
    //   2. PUT bytes direct from the renderer — onProgress reflects the
    //      actual upstream transfer (cloud R2 or desktop ComfyUI STP),
    //      not a localhost → backend hop.
    //   3. /upload-finalize → backend tells the provider the bytes are in
    //
    // Both cloud (R2) and desktop (ComfyUI-Stimma) provider endpoints
    // configure permissive CORS for the renderer origin, so the direct
    // PUT works in either case. This is the only practical way to handle
    // multi-GB cloud LoRA uploads — bytes never transit the desktop
    // Python process, so neither the WKWebView XHR timeout nor any
    // backend body buffering gates us.
    const prepareResp = await axios.post(
      `${getToolsAPIBase()}/upload-prepare/${encodeURIComponent(fullToolId)}`,
      { parameter, filename: file.name, file_size: file.size },
    )
    const { upload_id, upload_url, upload_method, is_presigned } = prepareResp.data as {
      upload_id: string
      upload_url: string
      upload_method: string
      is_presigned: boolean
    }

    try {
      // For presigned URLs (R2) the URL is its own auth — must NOT send
      // our own Authorization header (would conflict with the Sigv4
      // signature and AWS would reject as "Multiple authentication
      // methods"). For non-presigned ComfyUI endpoints we likewise don't
      // send credentials — STP auth is handled at WebSocket setup, not
      // per-request on the asset path.
      await axios.put(upload_url, file, {
        method: upload_method as 'PUT',
        timeout: 0,
        transformRequest: [(data) => data],
        withCredentials: false,
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            onProgress(percent)
          }
        },
      })
    } catch (err: any) {
      const detail = err?.response?.data ?? err?.message ?? 'upload failed'
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }

    const finalizeResp = await axios.post(
      `${getToolsAPIBase()}/upload-finalize/${encodeURIComponent(fullToolId)}`,
      { upload_id },
    )

    // Clear cache so next fetch picks up new tool schemas
    clearCache()

    return finalizeResp.data
  }

  /**
   * Refresh tools from a provider (triggers re-discovery of LoRAs etc.)
   *
   * @param providerId - Optional provider ID. If not specified, refreshes all providers.
   */
  async function refreshProviderTools(providerId?: string): Promise<void> {
    const endpoint = providerId
      ? `${getToolsAPIBase()}/refresh/${providerId}`
      : `${getToolsAPIBase()}/refresh`
    await axios.post(endpoint)
    clearCache()  // Force refetch on next access
  }

  // Computed helpers
  const cachedProviders = computed(() => providersCache.value)
  const cachedTools = computed(() => toolsCache.value)
  const hasCache = computed(() => lastFetchTime.value > 0)

  // WebSocket subscription for provider status changes
  const { on, off } = useWebSocket()

  /**
   * Subscribe to provider/tool changes via WebSocket.
   * Listens for both provider_status_changed and tools_updated events.
   * Clears cache so next fetch gets fresh data.
   * Returns unsubscribe function.
   */
  function subscribeToProviderChanges(
    callback?: (data: { provider_id?: string; status?: string; tool_count?: number }) => void
  ): () => void {
    const handleStatusChange = (data: { provider_id: string; status: string; tool_count: number }) => {
      // Clear cache to force fresh fetch
      clearCache()
      // Call optional callback
      if (callback) {
        callback(data)
      }
    }

    const handleToolsUpdated = () => {
      // Clear cache to force fresh fetch
      clearCache()
      // Call optional callback with empty data
      if (callback) {
        callback({})
      }
    }

    on('provider_status_changed', handleStatusChange)
    on('tools_updated', handleToolsUpdated)

    return () => {
      off('provider_status_changed', handleStatusChange)
      off('tools_updated', handleToolsUpdated)
    }
  }

  /**
   * Get tool availability from cache
   */
  function getToolAvailability(fullToolId: string): ToolAvailability {
    const tool = toolsCache.value.find(t => t.full_tool_id === fullToolId)
    return tool?.availability || 'disconnected'
  }

  // ==========================================================================
  // Pinned Tools API
  // ==========================================================================

  /**
   * Pinned tool response from API
   */
  interface PinnedToolResponse {
    full_tool_id: string
    pin_order: number
    name: string | null
    task_type: string | null  // Primary task type
    task_types: string[]  // All task types
    provider_id: string | null
  }

  /**
   * Get all pinned tools for current profile
   */
  async function listPinnedTools(): Promise<PinnedToolResponse[]> {
    const response = await axios.get(`${getToolsAPIBase()}/pinned`)
    return response.data
  }

  /**
   * Pin a provider tool
   */
  async function pinProviderTool(fullToolId: string): Promise<PinnedToolResponse> {
    const response = await axios.post(`${getToolsAPIBase()}/pin`, {
      full_tool_id: fullToolId
    })
    return response.data
  }

  /**
   * Unpin a provider tool
   */
  async function unpinProviderTool(fullToolId: string): Promise<void> {
    await axios.delete(`${getToolsAPIBase()}/pin/${encodeURIComponent(fullToolId)}`)
  }

  /**
   * Reorder pinned tools
   */
  async function reorderPinnedTools(fullToolIds: string[]): Promise<void> {
    await axios.post(`${getToolsAPIBase()}/reorder-pins`, {
      full_tool_ids: fullToolIds
    })
  }

  // ==========================================================================
  // Tool State API
  // ==========================================================================

  /**
   * Tool state (working parameters)
   */
  interface ToolStateResponse {
    full_tool_id: string
    state: Record<string, any>
    updated_at: string | null
  }

  /**
   * Get the working state for a tool
   */
  async function getToolState(fullToolId: string): Promise<ToolStateResponse> {
    const response = await axios.get(`${getToolsAPIBase()}/state/${encodeURIComponent(fullToolId)}`)
    return response.data
  }

  /**
   * Save the working state for a tool
   */
  async function saveToolState(fullToolId: string, state: Record<string, any>): Promise<ToolStateResponse> {
    const response = await axios.put(`${getToolsAPIBase()}/state/${encodeURIComponent(fullToolId)}`, {
      state
    })
    return response.data
  }

  return {
    // Provider API methods
    listProviders,
    getProvider,
    listAllTools,
    fetchProvidersAndTools,
    getToolsGroupedByProvider,
    getToolsByTaskType,
    getTool,
    getProviderTool,
    isProviderAvailable,
    getAvailableTaskTypes,
    clearCache,
    refreshProviderTools,
    uploadToTool,

    // Availability helpers
    subscribeToProviderChanges,
    getToolAvailability,

    // Pinned tools API
    listPinnedTools,
    pinProviderTool,
    unpinProviderTool,
    reorderPinnedTools,

    // Tool state API
    getToolState,
    saveToolState,

    // Reactive state
    cachedProviders,
    cachedTools,
    hasCache,
  }
}
