/**
 * Where a model's requests go, in plain words — one line under every model name.
 *
 * Choosing a model is a decision about whose balance the request draws down, so
 * the line should say that outright. "via Stimma" read as a badge rather than a
 * statement, and "Stimma" is the app, the account, and the website all at once,
 * so it never actually answered the question.
 *
 * For a model you host there is no balance to name, so the line gives the host
 * instead — still answering "where does this go", and keeping every row the
 * same height.
 *
 * One helper, shared by every model picker, so the settings rows and the chat
 * composer can't drift into saying it two different ways.
 */

export interface FundingModel {
  source?: string
  provider_kind?: string
  provider_name?: string
  endpoint_url?: string
}

function endpointHost(url?: string): string {
  if (!url) return ''
  try { return new URL(url).host } catch { return url }
}

export function modelSourceLine(model?: FundingModel | null): string {
  if (!model) return ''
  if (model.source === 'stimma_cloud') return 'Uses Stimma Account credits'
  if (model.provider_kind === 'local' || model.source === 'endpoint') {
    return model.provider_name || endpointHost(model.endpoint_url) || 'Local endpoint'
  }
  // A ChatGPT subscription is not a balance that draws down per token — it is
  // a plan with usage windows. Saying "balance" would imply the wrong thing
  // about what running out looks like.
  if (model.provider_kind === 'chatgpt') return 'Uses your ChatGPT plan'
  return model.provider_name ? `Uses your ${model.provider_name} balance` : ''
}
