// What every element surface can do to an element, in one place, so the
// grid's context menu, the slideshow's ⋯ sheet, the info panel, the viewer and
// the chat all read the same data and run the same three verbs:
//
//   refineInChat  opens a new chat with the element attached
//   rename        inline in the viewer on desktop; a sheet on a phone; a small
//                 dialog from the grid's menu on desktop
//   setCover      pick one of the element's own media
//
// Surfaces name an element by the media id they hold (a library tile, the
// slideshow's item, a chat card's version). One element version is one media
// payload, so a detail read by media id never goes stale; edits return the
// element's new current version.
import { reactive, shallowRef, watch, type Ref } from 'vue'
import axios from 'axios'
import router from '../../router'
import { addToast, reportActionError } from '../../composables/useToasts'
import { getChatDraft } from '../../composables/useChatDraft'
import { useWorkingContext } from '../../composables/useWorkingContext'
import { useWebSocket } from '../../composables/useWebSocket'
import { applySavedElement } from './elementCache'

export interface ElementMediaSlot {
  key: string
  title: string
  status: string
  asset_id: number | null
  media_id: number | null
  file_format: string | null
  file_hash: string | null
  width: number | null
  height: number | null
  missing: boolean
  is_cover: boolean
}

export interface ElementLora {
  key: string
  display_name?: string
  fingerprint?: string
  model_family?: string
  default_weight?: number
}

export interface ElementFile {
  path: string
  name: string
  label: string
  mime_type: string | null
  size: number | null
}

export interface ElementDetail {
  asset_id: number
  revision_id: number
  revision_number: number
  media_id: number
  name: string
  kind: string
  description: string
  cover: { key: string; media_id: number | null; asset_id: number | null; missing: boolean } | null
  instructions_display: string
  media: ElementMediaSlot[]
  loras: ElementLora[]
  files: ElementFile[]
  created_at: string
  updated_at: string
}

export const elementUi = reactive({
  // Media id of the element being renamed / getting a new cover (the dialogs read these).
  renaming: null as number | null,
  coverPicking: null as number | null,
  // The open desktop viewer claims rename so it can edit its own title in place.
  inlineRenameHost: null as number | null,
  // Bumped on every saved change so open viewers reload.
  version: 0,
})

// By media id. Requests are shared so a card, a header and a viewer showing
// the same version make one read.
const cache = reactive(new Map<number, ElementDetail>())
const inflight = new Map<number, Promise<ElementDetail | null>>()

export function cachedElement(mediaId: number | null | undefined): ElementDetail | null {
  return mediaId == null ? null : cache.get(Number(mediaId)) || null
}

export function loadElement(mediaId: number, { force = false } = {}): Promise<ElementDetail | null> {
  const id = Number(mediaId)
  if (!force && cache.has(id)) return Promise.resolve(cache.get(id)!)
  if (!force && inflight.has(id)) return inflight.get(id)!
  const request = axios.get(`/api/elements/by-media/${id}`)
    .then(({ data }) => {
      cache.set(id, data)
      return data as ElementDetail
    })
    .catch(() => null)
    .finally(() => inflight.delete(id))
  inflight.set(id, request)
  return request
}

// A rename made anywhere else (another window, the agent) reaches every cached
// version of that element: reread them in place, so names never go stale.
let followingRenames = false
function followRenames() {
  if (followingRenames) return
  followingRenames = true
  useWebSocket().on('assets_updated', (data: any) => {
    if (!data?.fields?.includes('title')) return
    const ids = new Set((data.asset_ids || []).map(Number))
    for (const [id, detail] of cache) {
      if (ids.has(detail.asset_id)) void loadElement(id, { force: true })
    }
  })
}

/** The element a media id names, loaded on demand and following saved edits. */
export function useElement(mediaId: Ref<number | null | undefined>) {
  followRenames()
  const element = shallowRef<ElementDetail | null>(cachedElement(mediaId.value))
  watch(() => [mediaId.value, elementUi.version, cache.get(Number(mediaId.value))] as const, async ([id]) => {
    if (id == null) { element.value = null; return }
    const cached = cachedElement(id)
    if (cached) { element.value = cached; return }
    element.value = null
    const data = await loadElement(id)
    if (mediaId.value === id) element.value = data
  }, { immediate: true })
  return element
}

/** Save a direct edit to the element's current version. */
export async function saveElement(mediaId: number, patch: { name?: string; cover_member_key?: string }) {
  const current = cachedElement(mediaId) || await loadElement(mediaId)
  if (!current) return null
  try {
    const { data } = await axios.patch(`/api/elements/${current.asset_id}`, {
      ...patch,
      base_revision_id: current.revision_id,
    })
    // A rename keeps the version; a new cover makes a new one, and surfaces
    // that follow the current version move to its media id. Earlier versions
    // keep their own content and only take the new name.
    applySavedElement(cache, data)
    elementUi.version++
    return data as ElementDetail
  } catch (error: any) {
    if (error?.response?.status === 409) {
      await loadElement(mediaId, { force: true })
      elementUi.version++
    }
    reportActionError(`Couldn't save ${current.name}.`, error)
    return null
  }
}

/** "Character" from the manifest's "character". */
export function kindLabel(kind: string | null | undefined): string {
  const text = (kind || '').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ''
}

export const elementActions = {
  async refineInChat(mediaId: number | null | undefined) {
    if (mediaId == null) return
    const el = cachedElement(mediaId) || await loadElement(mediaId)
    try {
      const { data: chat } = await axios.post('/api/chats', { name: null, project_id: useWorkingContext().activeProjectId.value ?? null })
      // The element rides along as the first message's attachment; sending it
      // checks the element out for the agent.
      const draft = getChatDraft(Number(chat.id))
      if (!draft.attachments.some((a: any) => a.media_id === Number(mediaId))) {
        draft.attachments.push({
          media_id: Number(mediaId),
          file_format: 'stimmaelement',
          element: el ? { asset_id: el.asset_id, name: el.name, kind: el.kind } : undefined,
        })
      }
      await router.push({ name: 'chat', params: { id: chat.id } })
    } catch (error) {
      reportActionError("Couldn't open a chat.", error)
    }
  },
  async rename(mediaId: number | null | undefined) {
    if (mediaId == null) return
    await loadElement(mediaId)
    elementUi.renaming = Number(mediaId)
  },
  async setCover(mediaId: number | null | undefined) {
    if (mediaId == null) return
    const el = await loadElement(mediaId)
    if (el && !el.media.some(m => !m.missing && m.media_id != null)) {
      addToast(`${el.name} has no media to use as a cover.`, 'info')
      return
    }
    elementUi.coverPicking = Number(mediaId)
  },
}
