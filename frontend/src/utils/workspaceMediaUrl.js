import { rewriteUrl } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'

// A workspace file served to an <img>: the tag can't send the profile headers.
export function workspaceMediaUrl(src) {
  if (!src) return src
  const profileId = getCurrentProfileId()
  const pin = profileId ? getCachedPin(profileId) : null
  const url = new URL(src, 'http://stimma.local')
  if (profileId && !url.searchParams.has('profile')) url.searchParams.set('profile', profileId)
  if (pin && !url.searchParams.has('pin')) url.searchParams.set('pin', pin)
  return rewriteUrl(`${url.pathname}${url.search}${url.hash}`)
}
