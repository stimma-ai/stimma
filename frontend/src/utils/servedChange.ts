// A local server can change which model it serves at the same URL. The
// backend marks each saved model it no longer serves (`served: false`) and
// reports, per local provider, the served models not added yet
// (`served.unadded`). That is a swap to offer, not an error.

type ProviderModel = {
  id: string
  model_id: string
  name?: string | null
  enabled?: boolean
  served?: boolean
}

type ServedModel = { id: string; name?: string | null; context_length?: number | null }

type Provider = {
  kind?: string
  last_test_passed?: boolean | null
  models?: ProviderModel[]
  served?: { missing?: string[]; unadded?: ServedModel[] } | null
}

export type ServedChange = {
  missing: ProviderModel[]
  unadded: ServedModel[]
  /** The one served model that replaces the one gone, when that is clear. */
  target: ServedModel | null
  description: string
  verb: string
}

/** Whether a saved model is one its server no longer serves. */
export function isNotServed(model: ProviderModel | null | undefined): boolean {
  return model?.served === false
}

export function servedChange(provider: Provider | null | undefined): ServedChange | null {
  if (provider?.kind !== 'local') return null
  // A server that cannot be reached is a connection failure, shown as today.
  if (provider.last_test_passed === false) return null
  const missing = (provider.models || []).filter(model => model.enabled !== false && isNotServed(model))
  if (!missing.length) return null
  const unadded = provider.served?.unadded || []
  // Two gone and one new: it is not clear which one it replaces.
  const target = missing.length === 1 && unadded.length === 1 ? unadded[0] : null
  const names = missing.map(model => model.name || model.model_id)
  return {
    missing,
    unadded,
    target,
    description: target
      ? `Now serving ${target.name || target.id}`
      : `${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} no longer served`,
    verb: target ? 'Switch' : unadded.length ? 'Choose model' : '',
  }
}

type CatalogModel = { slug: string; status?: string | null }

/** Whether a saved choice is a model its server stopped serving: it waits for
 * the person to switch or choose, so nothing may move it in the meantime. */
export function isAwaitingSwitch(catalog: readonly CatalogModel[] | null | undefined, slug: string | null | undefined): boolean {
  return Boolean(slug) && (catalog || []).some(model => model.slug === slug && model.status === 'not_served')
}

/** The model a switch moved this choice to, or null when it did not move. */
export function replacementFor(slug: string | null | undefined, replaces: Record<string, string> | null | undefined): string | null {
  if (!slug || !replaces) return null
  return Object.prototype.hasOwnProperty.call(replaces, slug) ? replaces[slug] : null
}
