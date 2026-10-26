/**
 * Providers API composable
 * Handles all API calls for provider and tool management (Toolsv3)
 *
 * Providers are sources of tools (built-in, JSON-RPC external).
 * Tools are identified by full tool ID: provider_id:tool_id
 */
import axios from 'axios'
import { ref, computed, toRaw } from 'vue'
import { getApiBase } from '../apiConfig'
import { toolProviderDisplayName } from '../utils/stimmaCloud'
import { useWebSocket } from './useWebSocket'
import { getCurrentProfileId } from './useProfile'
import { getReadDeadlineMs } from '../utils/readDeadline'

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
  // STP presentation / provider state (absent for providers without them)
  state?: 'ready' | 'in_progress' | 'warning' | 'error' | null
  state_summary?: string | null
  attention?: 'update_available' | null
  management_url?: string | null
  icon?: string | null
  needs_setup_count?: number
  needs_setup_tool_ids?: string[]
}

/**
 * Tool summary from the catalog.
 *
 * Launcher, picker, search and menu surfaces render only these fields, so the
 * shared catalog asks the server for summaries (`view=summary`) and leaves the
 * full input/output schemas for when a tool is opened (`getProviderTool`).
 *
 * `parameter_outline` carries the schema facts send-to menus need to decide
 * where media can be sent; a full tool answers the same questions from its
 * `parameter_schema`. A server older than the summary view ignores the
 * parameter and returns full tools, which carry `parameter_schema` instead.
 */
export interface ProviderToolSummary {
  full_tool_id: string  // "provider_id:tool_id"
  tool_id: string
  name: string
  subtitle?: string | null  // Short description for UI
  task_type: string  // Primary task type (backward compat)
  task_types: string[]  // All task types this tool supports
  provider_id: string
  provider_name: string
  metadata: Record<string, any>  // Display keys only, in a summary
  model_vendor?: string | null  // STP model_vendor (brand mark hint)
  model?: string | null  // STP model identifier
  availability: ToolAvailability  // "available", "disconnected", "unconfigured"
  preview_frames?: boolean  // Provider streams in-flight preview frames
  /**
   * Summary only: the tool's media parameters with just the structural schema
   * keys (type, item limits, x-control, x-accept-media), shaped like a
   * parameter schema. Read it through `toolParameterProperties`.
   */
  parameter_outline?: { properties?: Record<string, Record<string, any>> }
  parameter_schema?: Record<string, any>
  output_schema?: Record<string, any>
  layout?: any[] | null
}

/**
 * Full tool descriptor, including its schemas.
 */
export interface ProviderTool extends ProviderToolSummary {
  parameter_schema: Record<string, any>
  output_schema: Record<string, any>
}

/** True when a catalog entry carries its full schemas (an older server, or a fetched tool). */
export function isFullTool(tool: ProviderToolSummary | null | undefined): tool is ProviderTool {
  return !!tool && typeof tool.parameter_schema === 'object' && tool.parameter_schema !== null
}

/**
 * Grouped tools by provider
 */
export interface ProviderWithTools {
  provider: Provider
  tools: ProviderToolSummary[]
}

export interface ProviderParameterOption {
  value: string
  label: string
  description?: string
  category?: string
  preview_url?: string
}

interface Catalog {
  providers: Provider[]
  tools: ProviderToolSummary[]
}

// Reactive state for caching
const providersCache = ref<Provider[]>([])
const toolsCache = ref<ProviderToolSummary[]>([])
const lastFetchTime = ref<number>(0)
const CACHE_TTL = 30000 // 30 seconds
// Server + profile the cache belongs to. Catalogs are per profile, so a reply
// that arrives after a switch must not be cached for (or served to) the next.
let cacheScope: string | null = null

function catalogScope() {
  return JSON.stringify([getApiBase() ?? null, getCurrentProfileId() ?? null])
}

// Request ordering for cache publication. A reply may fill the cache only if
// its request started after the last invalidation and after the request whose
// reply is already cached — an older read landing late never replaces newer
// data or revives a catalog that was cleared while it was in flight.
let catalogRequestSeq = 0
let catalogClearedAtSeq = 0
const publishedSeq = { providers: 0, tools: 0 }

function beginCatalogRead() {
  return { seq: ++catalogRequestSeq, scope: catalogScope() }
}

function mayPublish(read: { seq: number; scope: string }, kind: keyof typeof publishedSeq) {
  if (read.scope !== catalogScope()) return false
  if (read.seq <= catalogClearedAtSeq || read.seq <= publishedSeq[kind]) return false
  publishedSeq[kind] = read.seq
  return true
}

// A reply that lost to a newer one already cached for the same scope: callers
// get the newer cached data instead of the older reply.
function supersededInCache(read: { seq: number; scope: string }, kind: keyof typeof publishedSeq) {
  return read.scope === catalogScope() && cacheScope === read.scope && publishedSeq[kind] > read.seq
}

function normalizeProvider<T extends { provider_id?: string | null; provider_name?: string | null }>(provider: T): T {
  return {
    ...provider,
    provider_name: toolProviderDisplayName(provider),
  }
}

// Full tools (with schemas), read one at a time when a tool is opened. Each
// entry and read belongs to a scope and carries the request sequence number
// it started at. A full tool is current only if its read started at or after
// `fullToolFloor`: an invalidation (tools or provider changed, profile
// changed, socket recovery, explicit clear) raises the floor to "now", so a
// schema is never served across a change it may predate. A newer catalog
// revalidates full tools read before it (see revalidateFullTools), so a fresh
// catalog never sits next to an older full tool.
let fullToolFloor = 0
const fullTools = new Map<string, { tool: ProviderTool; seq: number }>()
const fullToolReads = new Map<string, SharedRead<ProviderTool> & { seq: number; scope: string }>()

function fullToolKey(fullToolId: string) {
  return JSON.stringify([catalogScope(), fullToolId])
}

function retireFullToolsBefore(seq: number) {
  fullToolFloor = Math.max(fullToolFloor, seq)
  for (const [key, entry] of fullTools) if (entry.seq < fullToolFloor) fullTools.delete(key)
  for (const [key, read] of fullToolReads) if (read.seq < fullToolFloor) fullToolReads.delete(key)
}

// What the catalog and a full tool both say about a tool. A full tool read
// before the current catalog that disagrees with it on any of these is older
// than the catalog (a change whose event was missed, say).
const CATALOG_FIELDS = ['name', 'availability', 'task_type', 'task_types', 'provider_name', 'model', 'model_vendor', 'preview_frames'] as const

function agreesWithCatalog(tool: ProviderTool) {
  const listed = toolsCache.value.find(t => t.full_tool_id === tool.full_tool_id)
  if (!listed) return false
  return CATALOG_FIELDS.every(field => JSON.stringify(listed[field] ?? null) === JSON.stringify(tool[field] ?? null))
}

// A newer catalog keeps the full tools it agrees with; the rest are read
// again when next asked.
function revalidateFullTools(catalogSeq: number) {
  for (const [key, entry] of fullTools) {
    if (entry.seq < catalogSeq && !agreesWithCatalog(entry.tool)) fullTools.delete(key)
  }
}

// Module-level cache clearing function (used by event handlers)
function clearToolsCache() {
  providersCache.value = []
  toolsCache.value = []
  lastFetchTime.value = 0
  cacheScope = null
  catalogClearedAtSeq = catalogRequestSeq
  retireFullToolsBefore(catalogRequestSeq + 1)
}

// Listen for tools-changed browser event (dispatched by useWebSocket on
// tools_updated, ahead of the socket bridge below, which clears again before
// notifying subscribers)
window.addEventListener('tools-changed', () => {
  console.log('[ProvidersApi] Received tools-changed, clearing cache')
  clearToolsCache()
})

// Clear tools cache on profile change (different profiles may have different tools)
window.addEventListener('profile-changed', () => {
  console.log('[ProvidersApi] Profile changed, clearing tools cache')
  clearToolsCache()
})

// One server change clears the catalog once, before any subscriber reacts.
// Subscribers then share the read of the new catalog: had each cleared on its
// own, a later clear would discard the read an earlier subscriber had just
// started for the very same change.
type CatalogChange = { provider_id?: string; status?: string; tool_count?: number }
const catalogChangeSubscribers = new Set<(data: CatalogChange) => void>()
let catalogEventsInstalled = false

function handleCatalogChange(data: CatalogChange | undefined) {
  console.log('[ProvidersApi] Tools or providers changed, clearing tools cache')
  clearToolsCache()
  for (const subscriber of [...catalogChangeSubscribers]) {
    try {
      subscriber(data ?? {})
    } catch (error) {
      console.error('[ProvidersApi] Provider change subscriber failed:', error)
    }
  }
}

async function readProviders(config: { signal?: AbortSignal } = {}): Promise<Provider[]> {
  const read = beginCatalogRead()
  const response = await axios.get(`${getToolsAPIBase()}/providers`, config)
  const providers = response.data.map(normalizeProvider)
  if (mayPublish(read, 'providers')) providersCache.value = providers
  else if (supersededInCache(read, 'providers')) return providersCache.value
  return providers
}

async function readToolSummaries(config: { signal?: AbortSignal } = {}): Promise<ProviderToolSummary[]> {
  const read = beginCatalogRead()
  const response = await axios.get(`${getToolsAPIBase()}/providers/tools`, {
    ...config,
    params: { view: 'summary' },
  })
  const tools: ProviderToolSummary[] = response.data.map(normalizeProvider)
  if (mayPublish(read, 'tools')) {
    toolsCache.value = tools
    lastFetchTime.value = Date.now()
    cacheScope = read.scope
    revalidateFullTools(read.seq)
  } else if (supersededInCache(read, 'tools')) {
    return toolsCache.value
  }
  return tools
}

// Providers and tools are read together: if either fails, the other is
// cancelled, and this settles only once both have, so a failure never leaves
// a sibling read running unseen.
async function readCatalog(signal: AbortSignal): Promise<Catalog> {
  const both = new AbortController()
  const abortBoth = () => both.abort()
  if (signal.aborted) both.abort()
  signal.addEventListener('abort', abortBoth)
  try {
    // Report the failure that caused the abort, not the sibling's AbortError.
    let firstError: unknown = null
    const failFast = <T>(read: Promise<T>) => read.catch((error) => {
      firstError ??= error
      both.abort()
      throw error
    })
    const [providers, tools] = await Promise.allSettled([
      failFast(readProviders({ signal: both.signal })),
      failFast(readToolSummaries({ signal: both.signal })),
    ])
    if (providers.status === 'rejected' || tools.status === 'rejected') throw firstError
    return { providers: providers.value, tools: tools.value }
  } finally {
    signal.removeEventListener('abort', abortBoth)
  }
}


/**
 * A read that callers share. Everyone who needs the same data while it is
 * being read waits on one request instead of starting their own. It is
 * bounded by the read deadline, since a stalled transport must not hold every
 * caller forever, and it is cancelled once every caller waiting on it has
 * given up.
 */
interface SharedRead<T> {
  controller: AbortController
  promise: Promise<T>
  waiting: number
  done: boolean
}

function startSharedRead<T>(run: (signal: AbortSignal) => Promise<T>, settled: () => void): SharedRead<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), getReadDeadlineMs())
  const read: SharedRead<T> = { controller, promise: null as unknown as Promise<T>, waiting: 0, done: false }
  read.promise = run(controller.signal).finally(() => {
    clearTimeout(timer)
    read.done = true
    settled()
  })
  // Each caller sees failures through its own wait; this keeps a read
  // everyone abandoned from reporting an unhandled rejection.
  read.promise.catch(() => {})
  return read
}

function readCancelledError() {
  return new DOMException('The read was cancelled', 'AbortError')
}

function waitForShared<T>(read: SharedRead<T>, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) return Promise.reject(readCancelledError())
  read.waiting++
  return new Promise<T>((resolve, reject) => {
    let left = false
    const leave = () => {
      if (left) return false
      left = true
      signal?.removeEventListener('abort', onAbort)
      read.waiting--
      return true
    }
    const onAbort = () => {
      if (!leave()) return
      if (read.waiting === 0 && !read.done) {
        read.done = true
        read.controller.abort()
      }
      reject(readCancelledError())
    }
    signal?.addEventListener('abort', onAbort)
    read.promise.then(
      (value) => { if (leave()) resolve(value) },
      (error) => { if (leave()) reject(error) },
    )
  })
}

type SharedCatalogRead = SharedRead<Catalog> & { scope: string; firstSeq: number }

let sharedCatalogRead: SharedCatalogRead | null = null

function joinable(read: SharedCatalogRead | null): read is SharedCatalogRead {
  // A read that started before the last invalidation may predate the change.
  return !!read && !read.done && read.scope === catalogScope() && read.firstSeq > catalogClearedAtSeq
}

function startSharedCatalogRead(): SharedCatalogRead {
  const scope = catalogScope()
  const firstSeq = catalogRequestSeq + 1
  const read: SharedCatalogRead = Object.assign(
    startSharedRead(readCatalog, () => { if (sharedCatalogRead === read) sharedCatalogRead = null }),
    { scope, firstSeq },
  )
  sharedCatalogRead = read
  return read
}

/**
 * Providers and tool summaries, with caching. A fresh cache answers at once;
 * otherwise the caller joins the catalog read already running for this server
 * and profile, or starts it. `forceRefresh` skips the cache and never joins a
 * read that started earlier (the caller needs data at least as new as the
 * call, typically right after changing a tool), but later callers join the
 * read it starts.
 */
function fetchCatalog(forceRefresh = false, config: { signal?: AbortSignal } = {}): Promise<Catalog> {
  const now = Date.now()
  if (!forceRefresh && lastFetchTime.value > 0 && cacheScope === catalogScope() && now - lastFetchTime.value < CACHE_TTL) {
    return Promise.resolve({
      providers: providersCache.value,
      tools: toolsCache.value,
    })
  }
  const read = !forceRefresh && joinable(sharedCatalogRead) ? sharedCatalogRead : startSharedCatalogRead()
  return waitForShared(read, config.signal)
}

/** How often a schema read is retried when a change lands while it is in flight. */
const FULL_TOOL_ATTEMPTS = 3

/**
 * The full tool, schemas included, for a tool that is being opened or run.
 * Read once and shared while in flight, until a change or a newer catalog
 * retires it. A catalog that already carries full tools (an older server)
 * answers directly. `fresh` always reads again (availability checks, retries).
 * An answer to a read that a change overtook is never returned or kept: the
 * read is made again, so the caller ends on the newer tool.
 */
async function fetchFullTool(
  fullToolId: string,
  { fresh = false, signal }: { fresh?: boolean; signal?: AbortSignal } = {},
): Promise<ProviderTool> {
  // Every caller gets its own copy, as when each read was its own request:
  // screens build working state on the tool they are handed.
  return copyTool(await readFullTool(fullToolId, fresh, signal, FULL_TOOL_ATTEMPTS))
}

function copyTool(tool: ProviderTool): ProviderTool {
  return JSON.parse(JSON.stringify(toRaw(tool)))
}

async function readFullTool(
  fullToolId: string,
  fresh: boolean,
  signal: AbortSignal | undefined,
  attempts: number,
): Promise<ProviderTool> {
  const key = fullToolKey(fullToolId)
  let read = fresh ? undefined : fullToolReads.get(key)
  if (!fresh) {
    const cached = fullTools.get(key)
    if (cached && cached.seq >= fullToolFloor) return cached.tool
    if (cacheScope === catalogScope()) {
      const listed = toolsCache.value.find(t => t.full_tool_id === fullToolId)
      if (isFullTool(listed)) return listed
    }
  }
  if (!read || read.done || read.seq < fullToolFloor) {
    const seq = ++catalogRequestSeq
    const scope = catalogScope()
    const started: SharedRead<ProviderTool> & { seq: number; scope: string } = Object.assign(
      startSharedRead(async (readSignal) => {
        const url = `${getToolsAPIBase()}/provider-tool/${encodeURIComponent(fullToolId)}`
        return normalizeProvider((await axios.get(url, { signal: readSignal })).data) as ProviderTool
      }, () => { if (fullToolReads.get(key) === started) fullToolReads.delete(key) }),
      { seq, scope },
    )
    fullToolReads.set(key, started)
    read = started
  }
  const tool = await waitForShared(read, signal)
  if (read.scope !== catalogScope()) return tool  // the caller's scope is gone; never cached
  // A change landed while this was in flight, or a newer catalog disagrees
  // with the answer: it may predate either, so read again.
  const overtaken = read.seq < fullToolFloor
    || (cacheScope === read.scope && publishedSeq.tools > read.seq && !agreesWithCatalog(tool))
  if (overtaken) {
    if (attempts > 1) return readFullTool(fullToolId, false, signal, attempts - 1)
    return tool
  }
  const current = fullTools.get(key)
  if (!current || current.seq < read.seq) fullTools.set(key, { tool, seq: read.seq })
  return tool
}

// Events can be missed only while the socket is down, so a reconnect after a
// disconnect counts as a change: the catalog and every full tool are read
// again. The first connect is not one.
let socketWasDown = false

export function useProvidersApi() {
  // The socket is opened by its first user; install the change bridge then
  // rather than at import.
  const { on } = useWebSocket()
  if (!catalogEventsInstalled) {
    catalogEventsInstalled = true
    on('tools_updated', handleCatalogChange)
    on('provider_status_changed', handleCatalogChange)
    on('websocket_disconnected', () => { socketWasDown = true })
    on('websocket_reconnected', () => {
      if (!socketWasDown) return
      socketWasDown = false
      handleCatalogChange({})
    })
  }

  async function searchToolOptions(
    fullToolId: string,
    parameter: string,
    query: string,
    limit = 100,
  ): Promise<ProviderParameterOption[]> {
    const response = await axios.post(`${getToolsAPIBase()}/options/search`, {
      full_tool_id: fullToolId,
      parameter,
      query,
      limit,
    })
    return Array.isArray(response.data?.options) ? response.data.options : []
  }

  /**
   * List all registered providers (always a fresh read).
   */
  async function listProviders(config: { signal?: AbortSignal } = {}): Promise<Provider[]> {
    return readProviders(config)
  }

  /**
   * Get a specific provider by ID
   */
  async function getProvider(providerId: string): Promise<Provider> {
    const response = await axios.get(`${getToolsAPIBase()}/providers/${providerId}`)
    return normalizeProvider(response.data)
  }

  /**
   * Summaries of every tool, including cached descriptors from disconnected
   * providers (for history and settings UI). Served from the shared catalog.
   */
  async function listAllTools(config: { signal?: AbortSignal } = {}): Promise<ProviderToolSummary[]> {
    return (await fetchCatalog(false, config)).tools
  }

  /**
   * Summaries of the tools that can be invoked right now.
   *
   * Menu/picker surfaces must use this rather than listAllTools(), which
   * intentionally includes cached descriptors from disconnected providers.
   */
  async function listAvailableTools(config: { signal?: AbortSignal } = {}): Promise<ProviderToolSummary[]> {
    return (await fetchCatalog(false, config)).tools.filter(t => t.availability === 'available')
  }

  /**
   * Get tools grouped by provider
   */
  async function getToolsGroupedByProvider(): Promise<ProviderWithTools[]> {
    const { providers, tools } = await fetchCatalog()

    return providers.map(provider => ({
      provider,
      tools: tools.filter(t => t.provider_id === provider.provider_id),
    }))
  }

  /**
   * Get tools filtered by task type.
   * Matches tools where ANY of their task_types includes the given type.
   */
  async function getToolsByTaskType(taskType: string): Promise<ProviderToolSummary[]> {
    const { tools } = await fetchCatalog()
    return tools.filter(t => {
      const toolTaskTypes = t.task_types?.length ? t.task_types : [t.task_type]
      return toolTaskTypes.includes(taskType)
    })
  }

  /**
   * The full tool (schemas included) by full tool ID, or null if it is unknown.
   */
  async function getTool(fullToolId: string): Promise<ProviderTool | null> {
    try {
      return await fetchFullTool(fullToolId)
    } catch {
      return null
    }
  }

  /**
   * The full tool (schemas included) by full ID, shared and cached until a
   * change or a newer catalog retires it; `fresh` reads it again regardless.
   * Bounded by the read deadline; `signal` lets a caller stop waiting.
   */
  async function getProviderTool(fullToolId: string, options: { fresh?: boolean; signal?: AbortSignal } = {}): Promise<ProviderTool> {
    return fetchFullTool(fullToolId, options)
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
    const { tools } = await fetchCatalog()
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
    clearToolsCache()
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

  /**
   * Subscribe to provider/tool changes (provider_status_changed and
   * tools_updated). The shared cache is already cleared when the callback
   * runs, so the next fetch reads the new catalog.
   * Returns unsubscribe function.
   */
  function subscribeToProviderChanges(callback?: (data: CatalogChange) => void): () => void {
    const subscriber = (data: CatalogChange) => callback?.(data)
    catalogChangeSubscribers.add(subscriber)
    return () => {
      catalogChangeSubscribers.delete(subscriber)
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
    provider_name: string | null
  }

  /**
   * Get all pinned tools for current profile
   */
  async function listPinnedTools(): Promise<PinnedToolResponse[]> {
    const response = await axios.get(`${getToolsAPIBase()}/pinned`)
    return response.data.map(normalizeProvider)
  }

  /**
   * Pin a provider tool
   */
  async function pinProviderTool(fullToolId: string): Promise<PinnedToolResponse> {
    const response = await axios.post(`${getToolsAPIBase()}/pin`, {
      full_tool_id: fullToolId
    })
    return normalizeProvider(response.data)
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
    searchToolOptions,
    // Provider API methods
    listProviders,
    getProvider,
    listAllTools,
    listAvailableTools,
    fetchProvidersAndTools: fetchCatalog,
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
