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

export function nextComfyUIIdentity(providers: ToolProviderIdentity[]): { id: string; name: string } {
  const usedIds = new Set(providers.map(provider => String(provider.id || '').toLowerCase()))
  if (!usedIds.has('comfyui')) return { id: 'comfyui', name: 'ComfyUI' }

  let suffix = 2
  while (usedIds.has(`comfyui-${suffix}`)) suffix += 1
  return { id: `comfyui-${suffix}`, name: `ComfyUI ${suffix}` }
}

const CONNECTION_FIELDS = new Set([
  'url',
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
  return freshProviders.map(provider => {
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
}
