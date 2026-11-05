import { ref, readonly } from 'vue'
import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from './useProfile'
import { withReadDeadline } from '../utils/readDeadline'

const enabled = ref(false)
export const flowsEnabled = readonly(enabled)
export const savingFlowsPreference = ref(false)
let loadedScope = ''
let pending: { key: string; promise: Promise<void> } | null = null
const scope = () => `${getApiBase()}\n${getCurrentProfileId()}`

/** Profile-scoped, with no cached opt-in from another server or profile. */
export async function loadFlowsPreference() {
  const key = scope()
  if (loadedScope === key) return
  if (pending?.key === key) return pending.promise
  enabled.value = false
  const promise = withReadDeadline(async signal => {
    const response = await fetch(`${getApiBase()}/preferences/experimental_flows`, { signal })
    if (!response.ok && response.status !== 404) throw new Error(`Could not load Flows preference: ${response.status}`)
    const value = response.ok ? (await response.json()).value?.enabled === true : false
    if (scope() === key && loadedScope !== key) {
      enabled.value = value
      loadedScope = key
    }
  }).finally(() => { if (pending?.promise === promise) pending = null })
  pending = { key, promise }
  return promise
}

export async function setFlowsEnabled(value: boolean) {
  savingFlowsPreference.value = true
  const key = scope()
  try {
    const response = await fetch(`${getApiBase()}/preferences/experimental_flows`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: value }),
    })
    if (!response.ok) throw new Error(`Could not save Flows preference: ${response.status}`)
    if (scope() === key) {
      enabled.value = value
      loadedScope = key
    }
  } finally { savingFlowsPreference.value = false }
}

window.addEventListener('profile-changed', () => {
  enabled.value = false
  loadedScope = ''
  pending = null
})
