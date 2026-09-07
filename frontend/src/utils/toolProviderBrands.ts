export const DEFAULT_COMFYUI_STP_URL = 'ws://localhost:8188/stp-v1'

type ToolProviderIdentity = {
  id?: string | null
  name?: string | null
  provider_name?: string | null
}

export function isComfyUIProvider(provider: ToolProviderIdentity | null | undefined): boolean {
  if (!provider) return false
  const identity = [provider.id, provider.name, provider.provider_name]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
  return identity.includes('comfyui')
}

// Draw Things is a bundled local engine (macOS): identified by the sidecar
// the backend launches for it, never by a user-typed name.
export const DRAWTHINGS_SIDECAR = 'drawthings'

export function isDrawThingsProvider(provider: (ToolProviderIdentity & { sidecar?: string | null }) | null | undefined): boolean {
  return !!provider && provider.sidecar === DRAWTHINGS_SIDECAR
}

export function nextDrawThingsIdentity(providers: ToolProviderIdentity[]): { id: string; name: string } {
  const usedIds = new Set(providers.map(provider => String(provider.id || '').toLowerCase()))
  if (!usedIds.has(DRAWTHINGS_SIDECAR)) return { id: DRAWTHINGS_SIDECAR, name: 'Draw Things' }
  let suffix = 2
  while (usedIds.has(`${DRAWTHINGS_SIDECAR}-${suffix}`)) suffix += 1
  return { id: `${DRAWTHINGS_SIDECAR}-${suffix}`, name: `Draw Things ${suffix}` }
}

export function nextComfyUIIdentity(providers: ToolProviderIdentity[]): { id: string; name: string } {
  const usedIds = new Set(providers.map(provider => String(provider.id || '').toLowerCase()))
  if (!usedIds.has('comfyui')) return { id: 'comfyui', name: 'ComfyUI' }

  let suffix = 2
  while (usedIds.has(`comfyui-${suffix}`)) suffix += 1
  return { id: `comfyui-${suffix}`, name: `ComfyUI ${suffix}` }
}

const CONNECTION_FIELDS = new Set([
  'url',
  'sidecar',
  'auth_token',
  'command',
  'args',
  'working_dir',
  'api_key',
  'type',
])

export function toolProviderUpdateStartsConnection(update: Record<string, unknown>): boolean {
  if (update.enabled === false) return false
  if (update.enabled === true) return true
  return Object.keys(update).some(field => CONNECTION_FIELDS.has(field))
}

type ToolProviderStatus = ToolProviderIdentity & {
  enabled?: boolean
  status?: string | null
  [key: string]: unknown
}

export function preserveConnectingToolProviderStatuses(
  previousProviders: ToolProviderStatus[],
  freshProviders: ToolProviderStatus[],
): ToolProviderStatus[] {
  const previousById = new Map(previousProviders.map(provider => [provider.id, provider]))
  const merged = freshProviders.map(provider => {
    const previous = previousById.get(provider.id)
    if (
      previous?.status === 'connecting'
      && provider.status === 'disconnected'
      && provider.enabled !== false
    ) {
      return { ...provider, status: 'connecting' }
    }
    return provider
  })
  // A provider created moments ago can be missing from the next settings
  // read until the backend's config watcher reloads. Keep the optimistic
  // entry so guided setup screens don't blink back to their initial state.
  const freshIds = new Set(freshProviders.map(provider => provider.id))
  for (const previous of previousProviders) {
    if (previous.status === 'connecting' && !freshIds.has(previous.id)) merged.push(previous)
  }
  return merged
}
