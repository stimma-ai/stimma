/**
 * Share-link session logic: one session per open share dialog.
 *
 * Every piece of state lives inside the session object, so two dialogs (or a
 * dialog reopened for another item) never see each other's results. The
 * functions that reach outside (fetch, the provenance builder) are injected so
 * the whole flow runs under `node --test` with a mocked fetch.
 *
 * Endpoints (desktop backend, relative /api so the global fetch wrapper adds
 * the server origin and profile headers):
 *   GET    /api/share/status
 *   GET    /api/share/check-username?username=
 *   POST   /api/share/setup-identity
 *   GET    /api/share/links?media_id=        this item's existing links
 *   GET    /api/share/links?limit=&offset=   every link (Settings › Shared links)
 *   DELETE /api/share/links/{shortcode}
 *   POST   /api/share/suggest-title
 *   POST   /api/share/pre-check
 *   POST   /api/share
 */
import { computed, ref, shallowRef, watch, type Ref } from 'vue'
import { formatDuration, getMediaType } from '../utils/mediaTypes.ts'

export type ShareReasonCode = 'signed_out' | 'auth_expired' | 'privacy_lockdown' | 'banned' | 'unavailable'

export interface ShareAccount {
  username: string | null
  display_name?: string | null
  avatar_url?: string | null
}

export interface ShareStatus {
  can_share: boolean
  reason_code: ShareReasonCode | null
  reason: string | null
  identity_required: boolean
  account: ShareAccount | null
}

export interface ShareLink {
  shortcode: string
  url: string
  title: string | null
  status: string
  media_type: string | null
  view_count: number
  created_at: string | null
  thumbnail_url: string | null
}

export interface PreCheckResult {
  blocked: boolean
  decision: string | null
  nsfw: boolean
  reason: string | null
  size_bytes: number | null
  too_large: boolean
  media_type: string | null
  unsupported_reason: string | null
}

export interface ShareResult {
  shortcode: string
  url: string
  status: string | null
  media_type: string | null
}

export type SharePhase =
  | 'idle'
  | 'loading'
  | 'cant-share'
  | 'username'
  | 'links'
  | 'form'
  | 'uploading'
  | 'created'
  | 'error'

/** The one status line under the form. Null = nothing to say. */
export type ShareStatusSlot = 'checking' | 'review' | 'blocked' | 'too-large' | 'unsupported' | null

export interface ShareMedia {
  id: number
  [key: string]: unknown
}

export interface ShareDeps {
  fetch?: typeof fetch
  /** Public provenance for the item ("how it was made"), or null when there is none. */
  buildPublicProvenance?: (media: ShareMedia) => unknown | null
  /** Debounce for re-running the pre-check after title/description edits. */
  precheckDebounceMs?: number
  /** Debounce for the username availability check. */
  usernameDebounceMs?: number
}

export const USERNAME_PATTERN = /^[a-z0-9_-]{3,24}$/

/** Client-side username validation; null = valid. Mirrors the cloud's rule. */
export function validateUsername(value: string): string | null {
  const v = value.trim()
  if (!v) return null
  if (v.length < 3) return 'At least 3 characters'
  if (v.length > 24) return 'At most 24 characters'
  if (!USERNAME_PATTERN.test(v)) return 'Use lowercase letters, numbers, hyphens and underscores'
  return null
}

/**
 * Normalize /api/share/status. Older backends send only `reason`; infer the
 * code from it so the dialog can still pick the right state.
 */
export function normalizeStatus(data: any): ShareStatus {
  const reason: string | null = data?.reason ?? null
  let code: ShareReasonCode | null = data?.reason_code ?? null
  const identityRequired = !!data?.identity_required
  if (!data?.can_share && !code && !identityRequired) {
    const r = (reason || '').toLowerCase()
    if (r.includes('lockdown') || r.includes('privacy')) code = 'privacy_lockdown'
    else if (r.includes('expired')) code = 'auth_expired'
    else if (r.includes('suspended') || r.includes('banned')) code = 'banned'
    else if (r.includes('signed in') || r.includes('sign in')) code = 'signed_out'
    else code = 'unavailable'
  }
  const account = data?.account
    ? {
        username: data.account.username ?? null,
        display_name: data.account.display_name ?? null,
        avatar_url: data.account.avatar_url ?? null,
      }
    : data?.username
      ? { username: data.username, display_name: null, avatar_url: null }
      : null
  return {
    can_share: !!data?.can_share,
    reason_code: data?.can_share ? null : code,
    reason,
    identity_required: identityRequired,
    account,
  }
}

export function normalizeLink(raw: any): ShareLink {
  return {
    shortcode: String(raw?.shortcode ?? ''),
    url: String(raw?.url ?? ''),
    title: raw?.title ?? null,
    status: String(raw?.status ?? 'approved'),
    media_type: raw?.media_type ?? null,
    view_count: Number(raw?.view_count ?? 0) || 0,
    created_at: raw?.created_at ?? null,
    thumbnail_url: raw?.thumbnail_url ?? null,
  }
}

function linksFrom(data: any): any[] {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.links)) return data.links
  if (Array.isArray(data?.items)) return data.items
  return []
}

export function normalizePreCheck(data: any): PreCheckResult {
  return {
    blocked: !!data?.blocked,
    decision: data?.decision ?? null,
    nsfw: !!data?.nsfw,
    reason: data?.reason ?? null,
    size_bytes: typeof data?.size_bytes === 'number' ? data.size_bytes : null,
    too_large: !!data?.too_large,
    media_type: data?.media_type ?? null,
    unsupported_reason: data?.unsupported_reason ?? null,
  }
}

export function isInReview(status: string | null | undefined): boolean {
  return status === 'quarantined' || status === 'pending' || status === 'in_review'
}

/** One friendly sentence for a failed create. */
const ERROR_CODE_COPY: Record<string, string> = {
  signed_out: 'You’re signed out. Sign in, then try again.',
  auth_expired: 'Your sign-in expired. Sign in again, then try again.',
  privacy_lockdown: 'Sharing is off in Privacy Lockdown.',
  too_large: 'This item is too large to share as a link.',
  unsupported: 'This kind of item can’t be shared as a link yet.',
  not_found: 'This item is no longer in your library.',
}

export function friendlyShareError(status: number | null, message: string | null | undefined, code?: string | null): string {
  if (code === 'blocked' && message) return message
  if (code === 'unsupported' && message) return message
  if (code && ERROR_CODE_COPY[code]) return ERROR_CODE_COPY[code]
  if (status === null) return "Couldn't reach Stimma. Check your connection and try again."
  if (status === 413) return 'This item is too large to share as a link.'
  if (status === 401) return 'Your sign-in expired. Sign in again, then try again.'
  const m = (message || '').trim()
  // Short, plain backend messages are already written for people; anything
  // that looks like a stack or a raw HTTP dump is not.
  if (m && m.length <= 160 && !/traceback|exception|errno|http\s*\d{3}|<html/i.test(m)) return m
  return 'Something went wrong while creating the link. Try again.'
}

/** 12.4 MB / 820 KB: decimal units, one decimal from MB up. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return ''
  if (bytes < 1000) return `${Math.round(bytes)} B`
  if (bytes < 1000 ** 2) return `${Math.round(bytes / 1000)} KB`
  if (bytes < 1000 ** 3) return `${(bytes / 1000 ** 2).toFixed(1)} MB`
  return `${(bytes / 1000 ** 3).toFixed(1)} GB`
}

const TYPE_LABELS: Record<string, string> = {
  image: 'Image', video: 'Video', audio: 'Audio', text: 'Markdown', vector: 'SVG',
  set: 'Set', grid: 'Grid', sprite: 'Sprite', package: 'Package', layout: 'Layout',
}

/** The one mono fact under the preview: "Sprite · 4 animations", "Audio · 0:32". */
export function shareTypeFact(
  item: { file_format?: unknown; width?: unknown; height?: unknown; duration?: unknown; file_size?: unknown; raw_metadata?: unknown } | null | undefined,
  extra: { animationCount?: number | null; sizeBytes?: number | null } = {},
): string {
  if (!item) return ''
  const type = getMediaType({ file_format: String(item.file_format || '') })
  const label = TYPE_LABELS[type] || 'Item'
  const w = Number(item.width), h = Number(item.height)
  const dims = w > 0 && h > 0 ? `${w} × ${h}` : ''
  const duration = formatDuration(Number(item.duration) || null)
  const size = formatBytes(extra.sizeBytes ?? (Number(item.file_size) || null))
  let detail = ''
  if (type === 'audio' || type === 'video') detail = duration || dims
  else if (type === 'sprite') detail = extra.animationCount ? `${extra.animationCount} ${extra.animationCount === 1 ? 'animation' : 'animations'}` : ''
  else if (type === 'package' || type === 'text') detail = size
  else if (type === 'set' || type === 'grid') detail = compositeShape(type, item.raw_metadata) || size
  else detail = dims || size
  return detail ? `${label} · ${detail}` : label
}

/** "4 items" for a set, "2 × 3" for a grid, from the manifest the scanner keeps. */
function compositeShape(type: 'set' | 'grid', raw: unknown): string {
  let doc: any = raw
  if (typeof raw === 'string') {
    try { doc = JSON.parse(raw) } catch { return '' }
  }
  if (!doc || typeof doc !== 'object') return ''
  if (type === 'grid') {
    const rows = Number(doc.rows), cols = Number(doc.cols)
    return rows > 0 && cols > 0 ? `${rows} × ${cols}` : ''
  }
  const n = Array.isArray(doc.items) ? doc.items.length : 0
  return n ? `${n} ${n === 1 ? 'item' : 'items'}` : ''
}

// --- "How it was made" preview --------------------------------------------------

export interface PublishedStepPreview {
  tool: string
  model: string | null
  prompt: string | null
  facts: string[]
  extras: string[]
}

const PROMPT_PREVIEW_CHARS = 220

function truncate(s: string, n: number) {
  const t = s.trim().replace(/\s+/g, ' ')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

/** Exactly the published fields, flattened for a compact read-only list. */
export function publishedStepsPreview(p: unknown): PublishedStepPreview[] {
  const steps = (p as { steps?: any[] })?.steps
  if (!Array.isArray(steps)) return []
  return steps.map((step) => {
    const facts: string[] = []
    for (const f of Array.isArray(step?.facts) ? step.facts : []) {
      if (f?.label && f?.value != null && f.value !== '') facts.push(`${f.label} ${f.value}`)
    }
    const extras: string[] = []
    const loras = Array.isArray(step?.loras) ? step.loras : []
    if (loras.length) extras.push(`LoRAs: ${loras.map((l: any) => (l?.weight != null ? `${l.name} ${l.weight}` : l?.name)).filter(Boolean).join(', ')}`)
    const inputs = Array.isArray(step?.inputs) ? step.inputs : []
    if (inputs.length) {
      const roles = [...new Set(inputs.map((i: any) => String(i?.role || '')).filter((r: string) => r && !/^input( image)?$/i.test(r)))]
      const count = inputs.length === 1 ? '1 input image' : `${inputs.length} input images`
      extras.push(roles.length ? `${count}: ${roles.join(', ')}` : count)
    }
    const edits = Array.isArray(step?.edits) ? step.edits : []
    if (edits.length) extras.push(`Edits: ${edits.join(', ')}`)
    if (step?.negativePrompt) extras.push(`Negative prompt: ${truncate(String(step.negativePrompt), 80)}`)
    return {
      tool: String(step?.tool || 'Step'),
      model: step?.model ? String(step.model) : null,
      prompt: step?.prompt ? truncate(String(step.prompt), PROMPT_PREVIEW_CHARS) : null,
      facts,
      extras,
    }
  })
}

async function readJson(response: Response): Promise<any> {
  try { return await response.json() } catch { return null }
}

function isAbort(err: unknown): boolean {
  return (err as Error)?.name === 'AbortError'
}

export function createShareSession(deps: ShareDeps = {}) {
  const doFetch: typeof fetch = deps.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args))
  const precheckDebounceMs = deps.precheckDebounceMs ?? 700
  const usernameDebounceMs = deps.usernameDebounceMs ?? 400

  const phase = ref<SharePhase>('idle')
  const media = shallowRef<ShareMedia | null>(null)
  const status = ref<ShareStatus | null>(null)
  const links = ref<ShareLink[]>([])

  const title = ref('')
  const description = ref('')
  const titleTouched = ref(false)
  const suggesting = ref(false)

  const includeProvenance = ref(true)
  const matureManual = ref(false)

  const preChecking = ref(false)
  const preCheck = ref<PreCheckResult | null>(null)

  const result = ref<ShareResult | null>(null)
  const error = ref<string | null>(null)

  const usernameInput = ref('')
  const usernameChecking = ref(false)
  const usernameAvailable = ref<boolean | null>(null)
  const usernameError = ref<string | null>(null)
  const usernameSubmitting = ref(false)

  const provenance = shallowRef<unknown | null>(null)

  // Generation counter: a response for a previous start() never lands.
  let generation = 0
  let suggestController: AbortController | null = null
  let precheckController: AbortController | null = null
  let usernameController: AbortController | null = null
  let precheckTimer: ReturnType<typeof setTimeout> | null = null
  let usernameTimer: ReturnType<typeof setTimeout> | null = null
  // Set while start()/suggest write title/description so the watcher can
  // tell a programmatic fill from an edit.
  let quietEdit = false

  const account = computed(() => status.value?.account ?? null)
  const reasonCode = computed(() => status.value?.reason_code ?? null)
  const mature = computed(() => !!preCheck.value?.nsfw || matureManual.value)
  const matureLocked = computed(() => !!preCheck.value?.nsfw)
  const blocked = computed(() => !!preCheck.value && (preCheck.value.blocked || preCheck.value.decision === 'rejected'))
  const sizeBytes = computed<number | null>(() => {
    if (preCheck.value?.size_bytes != null) return preCheck.value.size_bytes
    const s = Number(media.value?.file_size)
    return Number.isFinite(s) && s > 0 ? s : null
  })

  const statusSlot = computed<ShareStatusSlot>(() => {
    if (preChecking.value) return 'checking'
    const p = preCheck.value
    if (!p) return null
    if (p.unsupported_reason) return 'unsupported'
    if (p.too_large) return 'too-large'
    if (p.blocked || p.decision === 'rejected') return 'blocked'
    if (p.decision === 'quarantined') return 'review'
    return null
  })

  const canCreate = computed(() => (
    phase.value === 'form'
    && !preChecking.value
    && !!media.value
    && !(preCheck.value && (preCheck.value.blocked || preCheck.value.decision === 'rejected' || preCheck.value.too_large || preCheck.value.unsupported_reason))
  ))

  function abortAll() {
    suggestController?.abort(); suggestController = null
    precheckController?.abort(); precheckController = null
    usernameController?.abort(); usernameController = null
    if (precheckTimer) { clearTimeout(precheckTimer); precheckTimer = null }
    if (usernameTimer) { clearTimeout(usernameTimer); usernameTimer = null }
    suggesting.value = false
    preChecking.value = false
    usernameChecking.value = false
  }

  function resetForm() {
    quietEdit = true
    title.value = ''
    description.value = ''
    quietEdit = false
    titleTouched.value = false
    includeProvenance.value = true
    matureManual.value = false
    preCheck.value = null
    result.value = null
    error.value = null
  }

  async function loadStatus(gen: number): Promise<ShareStatus | null> {
    try {
      const response = await doFetch('/api/share/status')
      const data = await readJson(response)
      if (gen !== generation) return null
      if (!response.ok || !data) {
        return { can_share: false, reason_code: 'unavailable', reason: null, identity_required: false, account: null }
      }
      return normalizeStatus(data)
    } catch {
      if (gen !== generation) return null
      return { can_share: false, reason_code: 'unavailable', reason: null, identity_required: false, account: null }
    }
  }

  async function loadItemLinks(gen: number): Promise<ShareLink[]> {
    if (!media.value) return []
    try {
      const response = await doFetch(`/api/share/links?media_id=${encodeURIComponent(String(media.value.id))}`)
      if (!response.ok) return []
      const data = await readJson(response)
      if (gen !== generation) return []
      return linksFrom(data).map(normalizeLink).filter(l => l.shortcode)
    } catch {
      return []
    }
  }

  /** Open the session for an item: status → (username | links | form). */
  async function start(item: ShareMedia) {
    abortAll()
    const gen = ++generation
    media.value = item
    status.value = null
    links.value = []
    usernameInput.value = ''
    usernameAvailable.value = null
    usernameError.value = null
    resetForm()
    try {
      provenance.value = deps.buildPublicProvenance ? (deps.buildPublicProvenance(item) ?? null) : null
    } catch {
      provenance.value = null
    }
    phase.value = 'loading'
    await proceed(gen)
  }

  async function proceed(gen: number) {
    phase.value = 'loading'
    const s = await loadStatus(gen)
    if (gen !== generation || !s) return
    status.value = s
    if (s.identity_required) { phase.value = 'username'; return }
    if (!s.can_share) { phase.value = 'cant-share'; return }
    const existing = await loadItemLinks(gen)
    if (gen !== generation) return
    links.value = existing
    if (existing.length > 0) phase.value = 'links'
    else enterForm()
  }

  /** Re-run the status check (after sign-in, or Try again on "can't reach"). */
  async function recheck() {
    abortAll()
    const gen = ++generation
    await proceed(gen)
  }

  function enterForm() {
    phase.value = 'form'
    void suggestTitle()
    void runPreCheck()
  }

  function createAnother() {
    resetForm()
    enterForm()
  }

  async function suggestTitle() {
    if (!media.value) return
    suggestController?.abort()
    const controller = new AbortController()
    suggestController = controller
    suggesting.value = true
    try {
      const response = await doFetch('/api/share/suggest-title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_id: media.value.id }),
        signal: controller.signal,
      })
      if (!response.ok) return
      const data = await readJson(response)
      if (controller.signal.aborted || titleTouched.value) return
      if (data?.title && !title.value.trim()) {
        quietEdit = true
        title.value = String(data.title)
        quietEdit = false
        // A suggested title is checked like a typed one; no reason to wait.
        void runPreCheck()
      }
    } catch (err) {
      if (!isAbort(err)) console.warn('[share] title suggestion failed:', err)
    } finally {
      if (suggestController === controller) {
        suggestController = null
        suggesting.value = false
      }
    }
  }

  async function runPreCheck() {
    if (!media.value) return
    if (precheckTimer) { clearTimeout(precheckTimer); precheckTimer = null }
    precheckController?.abort()
    const controller = new AbortController()
    precheckController = controller
    preChecking.value = true
    try {
      const response = await doFetch('/api/share/pre-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          media_id: media.value.id,
          title: title.value.trim() || undefined,
          description: description.value.trim() || undefined,
        }),
        signal: controller.signal,
      })
      const data = await readJson(response)
      if (controller.signal.aborted) return
      // A failed pre-check never blocks: moderation runs again at upload.
      preCheck.value = response.ok && data ? normalizePreCheck(data) : null
    } catch (err) {
      if (!isAbort(err)) preCheck.value = null
    } finally {
      if (precheckController === controller) {
        precheckController = null
        preChecking.value = false
      }
    }
  }

  function schedulePreCheck() {
    if (phase.value !== 'form') return
    if (precheckTimer) clearTimeout(precheckTimer)
    precheckTimer = setTimeout(() => { precheckTimer = null; void runPreCheck() }, precheckDebounceMs)
  }

  watch([title, description], () => {
    if (quietEdit) return
    if (!titleTouched.value && title.value) {
      titleTouched.value = true
      // The person is typing; a late suggestion must not overwrite them.
      suggestController?.abort()
      suggestController = null
      suggesting.value = false
    }
    schedulePreCheck()
  }, { flush: 'sync' })

  function setTitle(v: string) {
    titleTouched.value = true
    suggestController?.abort(); suggestController = null; suggesting.value = false
    title.value = v
  }

  // --- Username setup ---------------------------------------------------------

  function setUsername(v: string) {
    const value = v.toLowerCase().replace(/\s+/g, '')
    usernameInput.value = value
    usernameAvailable.value = null
    usernameController?.abort(); usernameController = null
    usernameChecking.value = false
    if (usernameTimer) { clearTimeout(usernameTimer); usernameTimer = null }
    usernameError.value = validateUsername(value)
    if (usernameError.value || !value) return
    usernameTimer = setTimeout(() => { usernameTimer = null; void checkUsername(value) }, usernameDebounceMs)
  }

  async function checkUsername(value: string) {
    const controller = new AbortController()
    usernameController = controller
    usernameChecking.value = true
    try {
      const response = await doFetch(`/api/share/check-username?username=${encodeURIComponent(value)}`, { signal: controller.signal })
      const data = await readJson(response)
      if (controller.signal.aborted || value !== usernameInput.value) return
      if (data?.error) { usernameError.value = String(data.error); usernameAvailable.value = false }
      else if (data?.available) { usernameAvailable.value = true; usernameError.value = null }
      else { usernameAvailable.value = false; usernameError.value = 'That username is taken' }
    } catch (err) {
      if (!isAbort(err) && value === usernameInput.value) usernameError.value = "Couldn't check that username"
    } finally {
      if (usernameController === controller) {
        usernameController = null
        usernameChecking.value = false
      }
    }
  }

  const canSubmitUsername = computed(() => (
    !!usernameInput.value
    && !validateUsername(usernameInput.value)
    && !usernameChecking.value
    && usernameAvailable.value !== false
    && !usernameSubmitting.value
  ))

  async function submitUsername() {
    const value = usernameInput.value
    const invalid = validateUsername(value) || (!value ? 'Choose a username' : null)
    if (invalid) { usernameError.value = invalid; return false }
    usernameSubmitting.value = true
    usernameError.value = null
    const gen = generation
    try {
      const response = await doFetch('/api/share/setup-identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: value }),
      })
      const data = await readJson(response)
      if (gen !== generation) return false
      if (!response.ok || !data?.success) {
        usernameError.value = data?.error ? String(data.error) : "Couldn't save that username. Try again."
        return false
      }
    } catch {
      usernameError.value = "Couldn't reach Stimma. Try again."
      return false
    } finally {
      usernameSubmitting.value = false
    }
    await proceed(gen)
    return true
  }

  // --- Create -------------------------------------------------------------------

  async function create() {
    if (!media.value) return null
    if (phase.value !== 'form' && phase.value !== 'error') return null
    const gen = generation
    if (precheckTimer) { clearTimeout(precheckTimer); precheckTimer = null }
    suggestController?.abort()
    phase.value = 'uploading'
    error.value = null
    let httpStatus: number | null = null
    try {
      const response = await doFetch('/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          media_id: media.value.id,
          title: title.value.trim() || null,
          description: description.value.trim() || null,
          nsfw_override: mature.value,
          provenance: includeProvenance.value ? (provenance.value ?? null) : null,
        }),
      })
      httpStatus = response.status
      const data = await readJson(response)
      if (gen !== generation) return null
      if (!response.ok || !data?.success || !data?.url) {
        const message = data?.error ?? (typeof data?.detail === 'string' ? data.detail : null)
        throw Object.assign(new Error(message || ''), { httpStatus, errorCode: data?.error_code ?? null })
      }
      result.value = {
        shortcode: String(data.shortcode ?? ''),
        url: String(data.url),
        status: data.status ?? null,
        media_type: data.media_type ?? null,
      }
      phase.value = 'created'
      return result.value
    } catch (err) {
      if (gen !== generation) return null
      const s = (err as any)?.httpStatus ?? httpStatus
      error.value = friendlyShareError(s ?? null, (err as Error)?.message, (err as any)?.errorCode)
      phase.value = 'error'
      return null
    }
  }

  /** Error → back to the filled-in form. */
  function backToForm() {
    error.value = null
    phase.value = 'form'
  }

  async function deleteLink(shortcode: string) {
    const response = await doFetch(`/api/share/links/${encodeURIComponent(shortcode)}`, { method: 'DELETE' })
    if (!response.ok) {
      const data = await readJson(response)
      throw new Error(data?.error || "Couldn't delete that link")
    }
    links.value = links.value.filter(l => l.shortcode !== shortcode)
    if (phase.value === 'links' && links.value.length === 0) createAnother()
  }

  function dispose() {
    generation++
    abortAll()
    phase.value = 'idle'
  }

  return {
    // state
    phase,
    media,
    status,
    account,
    reasonCode,
    links,
    title,
    description,
    suggesting,
    includeProvenance,
    provenance,
    matureManual,
    mature,
    matureLocked,
    preChecking,
    preCheck,
    blocked,
    statusSlot,
    sizeBytes,
    canCreate,
    result,
    error,
    usernameInput,
    usernameChecking,
    usernameAvailable,
    usernameError,
    usernameSubmitting,
    canSubmitUsername,
    // actions
    start,
    recheck,
    createAnother,
    setTitle,
    setUsername,
    submitUsername,
    create,
    backToForm,
    deleteLink,
    runPreCheck,
    dispose,
  }
}

export type ShareSession = ReturnType<typeof createShareSession>

/** Composable form: a fresh session per caller (never shared module state). */
export function useShare(deps: ShareDeps = {}): ShareSession {
  return createShareSession(deps)
}

// --- Settings › Shared links ------------------------------------------------------

export interface SharedLinksDeps {
  fetch?: typeof fetch
  pageSize?: number
}

function friendlyListError(message: unknown): string {
  const m = typeof message === 'string' ? message.trim() : ''
  return m && m.length <= 120 && !/traceback|exception|http\s*\d{3}/i.test(m) ? m : "Couldn't load your shared links"
}

export function createSharedLinksList(deps: SharedLinksDeps = {}) {
  const doFetch: typeof fetch = deps.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args))
  const pageSize = deps.pageSize ?? 30

  const items = ref<ShareLink[]>([])
  const status: Ref<ShareStatus | null> = ref(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const hasMore = ref(false)
  const error = ref<string | null>(null)
  let gen = 0

  async function fetchPage(offset: number) {
    const response = await doFetch(`/api/share/links?limit=${pageSize}&offset=${offset}`)
    const data = await readJson(response)
    if (!response.ok || (data?.error && !linksFrom(data).length)) throw new Error(friendlyListError(data?.error))
    const page = linksFrom(data).map(normalizeLink).filter(l => l.shortcode)
    let more: boolean
    if (typeof data?.has_more === 'boolean') more = data.has_more
    else if (typeof data?.total === 'number') more = offset + page.length < data.total
    else more = page.length === pageSize
    return { page, more }
  }

  async function load() {
    const g = ++gen
    loading.value = true
    error.value = null
    try {
      const sResponse = await doFetch('/api/share/status')
      const sData = await readJson(sResponse)
      if (g !== gen) return
      status.value = sResponse.ok && sData
        ? normalizeStatus(sData)
        : { can_share: false, reason_code: 'unavailable', reason: null, identity_required: false, account: null }
      // Signed out / lockdown: no list to show. Banned accounts still own
      // (and may delete) their links, so they load.
      const code = status.value.reason_code
      if (code === 'signed_out' || code === 'auth_expired' || code === 'privacy_lockdown' || code === 'unavailable') {
        items.value = []
        hasMore.value = false
        return
      }
      const { page, more } = await fetchPage(0)
      if (g !== gen) return
      items.value = page
      hasMore.value = more
    } catch (err) {
      if (g === gen) error.value = (err as Error)?.message || "Couldn't load your shared links"
    } finally {
      if (g === gen) loading.value = false
    }
  }

  async function loadMore() {
    if (loadingMore.value || !hasMore.value) return
    const g = gen
    loadingMore.value = true
    try {
      const { page, more } = await fetchPage(items.value.length)
      if (g !== gen) return
      const seen = new Set(items.value.map(l => l.shortcode))
      items.value = [...items.value, ...page.filter(l => !seen.has(l.shortcode))]
      hasMore.value = more
    } catch (err) {
      if (g === gen) error.value = (err as Error)?.message || "Couldn't load more links"
    } finally {
      loadingMore.value = false
    }
  }

  async function remove(shortcode: string) {
    const response = await doFetch(`/api/share/links/${encodeURIComponent(shortcode)}`, { method: 'DELETE' })
    if (!response.ok) {
      const data = await readJson(response)
      throw new Error(data?.error || "Couldn't delete that link")
    }
    items.value = items.value.filter(l => l.shortcode !== shortcode)
  }

  return { items, status, loading, loadingMore, hasMore, error, load, loadMore, remove }
}
