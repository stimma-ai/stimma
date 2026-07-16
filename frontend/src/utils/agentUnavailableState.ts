export type AgentUnavailableState = 'privacy' | 'no-balance' | 'unavailable'

type AgentUnavailableStateInput = {
  privacyLockdownActive?: boolean
  isAuthenticated?: boolean
  cloudCredits?: number | string | null
  cloudStatus?: string | null
}

const NO_BALANCE_STATUSES = new Set([
  'insufficient_balance',
  'llm_insufficient_balance',
  'subscription_required',
  'subscription_error',
])

export function resolveAgentUnavailableState({
  privacyLockdownActive = false,
  isAuthenticated = false,
  cloudCredits = null,
  cloudStatus = null,
}: AgentUnavailableStateInput): AgentUnavailableState {
  if (privacyLockdownActive) return 'privacy'
  if (isAuthenticated) {
    if (cloudCredits != null && Number(cloudCredits) <= 0) return 'no-balance'
    if (cloudStatus && NO_BALANCE_STATUSES.has(cloudStatus)) return 'no-balance'
  }
  return 'unavailable'
}
