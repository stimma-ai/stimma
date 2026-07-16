import { STIMMA_CLOUD_PROVIDER_ID } from './stimmaCloud.ts'

type AvailableModel = {
  available?: boolean
  name?: string
  slug?: string
  source?: string
  resolved_slug?: string | null
}

// A signed-in Stimma account with zero balance can still list cloud models
// and keep the cloud tool provider connected (access is enforced per-request
// on the cloud side), so "usable" must be decided here from the balance.
export type StimmaCloudReadiness = {
  // true only when the account is signed in AND has a positive balance
  stimmaCloudUsable?: boolean
}

export function isSelectableModel(model: AvailableModel | null | undefined): boolean {
  return model?.available === true
}

export function isCatalogSelectableModel(
  models: readonly AvailableModel[],
  model: AvailableModel | null | undefined,
): boolean {
  if (!isSelectableModel(model)) return false
  if (model?.source !== 'auto' && model?.slug !== 'auto') return true
  if (!model.resolved_slug) return false
  return isSelectableModel(models.find(candidate => candidate.slug === model.resolved_slug))
}

export function selectableModelForSlug(
  models: readonly AvailableModel[],
  slug: string | null | undefined,
): AvailableModel | undefined {
  const selected = models.find(model => model.slug === slug)
  if (!isCatalogSelectableModel(models, selected)) return undefined
  const resolved = (selected?.source === 'auto' || selected?.slug === 'auto') && selected.resolved_slug
    ? models.find(model => model.slug === selected.resolved_slug)
    : selected
  return isSelectableModel(resolved) ? resolved : undefined
}

export function modelSelectionLabel(
  models: readonly AvailableModel[],
  slug: string | null | undefined,
): string {
  const selected = selectableModelForSlug(models, slug)
  if (selected?.name) return selected.name
  return models.some(model => isCatalogSelectableModel(models, model))
    ? 'Choose a model'
    : 'No models available'
}

type ToolProvider = {
  id?: string
  enabled?: boolean
  type?: string
  status?: string
  tool_count?: number | null
}

export function hasUsableLlmModel(
  models: readonly AvailableModel[],
  { stimmaCloudUsable = true }: StimmaCloudReadiness = {},
): boolean {
  // Dropping cloud models from the candidate list also invalidates an 'auto'
  // entry whose resolved_slug points at one of them.
  const candidates = stimmaCloudUsable
    ? models
    : models.filter(model => model.source !== 'stimma_cloud')
  return candidates.some(model => isCatalogSelectableModel(candidates, model))
}

export function hasUsableGenerationProvider(
  providers: readonly ToolProvider[],
  { stimmaCloudUsable = true }: StimmaCloudReadiness = {},
): boolean {
  return providers.some(provider => (
    (stimmaCloudUsable || provider.id !== STIMMA_CLOUD_PROVIDER_ID)
    && provider.enabled !== false
    && (provider.type === 'stdio' || provider.type === 'websocket')
    && provider.status === 'connected'
    && Number(provider.tool_count || 0) > 0
  ))
}
