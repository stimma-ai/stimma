/**
 * Backend-served images the app's provenance host draws that aren't library
 * media: reference files picked from disk, and the preprocessed previews a
 * ControlNet-style input was turned into (resolved and cached by the backend
 * on demand, then cached here per input for the session).
 */
import { reactive } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'

interface PreprocessedRef {
  sourcePath: string
  preprocessor: string
  params: unknown
}

function withAuth(url: string): string {
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let out = `${url}&profile=${encodeURIComponent(profileId)}`
  if (pin) out += `&pin=${encodeURIComponent(pin)}`
  return out
}

export function referenceFileUrl(filePath: string): string {
  return withAuth(`${getApiBase()}/generate/reference-file?path=${encodeURIComponent(filePath)}`)
}

const resolved = reactive<Record<string, string>>({})
const requested = new Set<string>()

function previewKey(ref: PreprocessedRef): string {
  return `${ref.sourcePath}_${ref.preprocessor}_${ref.params ? JSON.stringify(ref.params) : ''}`
}

async function resolvePreview(key: string, ref: PreprocessedRef) {
  try {
    const resp = await axios.post(`${getApiBase()}/generate/preprocess-controlnet`, {
      source_path: ref.sourcePath,
      preprocessor: ref.preprocessor,
      preprocessor_params: ref.params || null,
    })
    if (resp.data?.path) {
      resolved[key] = withAuth(`${getApiBase()}/generate/controlnet-preview?path=${encodeURIComponent(resp.data.path)}`)
    }
  } catch (err) {
    console.warn('Failed to resolve preprocessed image:', err)
  }
}

/**
 * The preview's URL once resolved, '' until then. The first call starts the
 * (deduplicated) resolution; the result arrives reactively.
 */
export function preprocessedUrl(ref: PreprocessedRef): string {
  const key = previewKey(ref)
  if (!resolved[key] && !requested.has(key)) {
    requested.add(key)
    queueMicrotask(() => { void resolvePreview(key, ref) })
  }
  return resolved[key] || ''
}
