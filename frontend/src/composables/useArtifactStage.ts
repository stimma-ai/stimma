/**
 * Chat artifact stage: standalone-ChatView-only state for the "iterating on
 * one deliverable" split view (design: plans/CHAT_ARTIFACTS.html, Mock A/B).
 *
 * Identity lives in the Asset/AssetRevision chain already used by the media
 * library (see useAssetApi). This composable just tracks which asset is
 * staged for a given chat, which revision is being viewed, and open/closed
 * UI state — no new backend concepts.
 */
import { ref, computed, watch, type Ref } from 'vue'
import type { WorkspaceFile } from '../utils/fileRefs'
import { useAssetApi } from './useAssetApi'
import { makeStorageKey } from '../utils/storageKeys'

export interface ArtifactRevision {
  id: number
  revision_number: number
  parent_revision_id: number | null
  note: string | null
  created_at: string
  media_id: number
  media_hash?: string | null
  filename?: string
  file_size?: number
  mime?: string
  file_format: string
  width?: number | null
  height?: number | null
}

export interface ArtifactMeta {
  asset_id: number
  revision_id: number
  revision_number: number
  note?: string | null
  title?: string | null
}

export const STAGE_MIN_WIDTH = 280
export const STAGE_MAX_WIDTH = 700
const STAGE_DEFAULT_WIDTH = 420

export function parseArtifactMeta(item: any): ArtifactMeta | null {
  if (!item || item.item_type !== 'media_display' || !item.item_metadata) return null
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    const artifact = metadata?.display_data?.artifact
    if (!artifact?.asset_id || !artifact?.revision_id) return null
    return artifact
  } catch {
    return null
  }
}

export function useArtifactStage(chatId: Ref<number | string | null>, items: Ref<any[]>) {
  const assetApi = useAssetApi()

  const stageOpen = ref(false)
  const workspaceFile = ref<WorkspaceFile | null>(null)
  function openFile(file: WorkspaceFile) {
    workspaceFile.value = file
    stageOpen.value = true
  }
  const assetId = ref<number | null>(null)
  const asset = ref<{ id: number; title: string | null; current_revision_id: number } | null>(null)
  const revisions = ref<ArtifactRevision[]>([])
  const viewedRevisionId = ref<number | null>(null)
  const loading = ref(false)
  const width = ref(STAGE_DEFAULT_WIDTH)
  const resizing = ref(false)

  // Closed-state is per chat AND asset: dismissing one artifact must not
  // suppress the next one the agent starts in the same chat.
  // Per-chat persisted panel state: whether it is open, the file it was
  // showing (or last showed, so a closed panel reopens onto the same file),
  // and the artifact asset the chat had at the time. Dismissing one artifact
  // must not suppress the next one the agent starts in the same chat, which is
  // why the asset id travels with the closed flag.
  interface PersistedStageState { open: boolean; file: WorkspaceFile | null; dismissedAssetId: number | null }
  // The asset whose panel the user explicitly closed; a different asset
  // arriving later still auto-opens.
  const dismissedAssetId = ref<number | null>(null)
  function stateKey(id: number | string) {
    return makeStorageKey('chat', id, 'artifact_stage_state')
  }
  function readState(id: number | string): PersistedStageState | null {
    try {
      const raw = localStorage.getItem(stateKey(id))
      return raw ? JSON.parse(raw) as PersistedStageState : null
    } catch { return null }
  }
  // Key bumped when the stage moved to the right of the chat (drag direction
  // flipped): widths stored under the old key would pin the chat column wide
  // and squeeze the stage on chats where the handle had been dragged.
  function widthKey(id: number | string) {
    return makeStorageKey('chat', id, 'artifact_chat_width')
  }
  function isUserClosed(forAssetId: number | null = assetId.value): boolean {
    return forAssetId != null && dismissedAssetId.value === forAssetId
  }

  // The most recent artifact-bearing item in the chat wins identity — this
  // stays live (recomputed on every WebSocket item) independent of whether
  // the panel itself is open, so chips keep working after the user closes it.
  const latestArtifactMeta = computed<ArtifactMeta | null>(() => {
    for (let i = items.value.length - 1; i >= 0; i--) {
      const meta = parseArtifactMeta(items.value[i])
      if (meta) return meta
    }
    return null
  })
  const latestArtifactAssetId = computed(() => latestArtifactMeta.value?.asset_id ?? null)

  const latestRevisionId = computed<number | null>(() => {
    if (!revisions.value.length) return null
    return revisions.value[revisions.value.length - 1].id
  })

  const viewedRevision = computed<ArtifactRevision | null>(() => {
    if (viewedRevisionId.value == null) return null
    return revisions.value.find(r => r.id === viewedRevisionId.value) || null
  })

  const onNewest = computed(() => {
    return viewedRevisionId.value != null && viewedRevisionId.value === latestRevisionId.value
  })

  function findRevision(revisionId: number): ArtifactRevision | null {
    return revisions.value.find(r => r.id === revisionId) || null
  }

  // Loads/refreshes the revision chain for `id`. Does not touch stageOpen —
  // callers decide whether the panel should be visible.
  async function syncAsset(id: number, { keepViewed = false } = {}) {
    const switchingAsset = assetId.value !== id
    assetId.value = id
    loading.value = true
    try {
      const data = await assetApi.getRevisions(id)
      asset.value = data.asset
      revisions.value = data.revisions || []
      const latest = revisions.value[revisions.value.length - 1] || null
      if (switchingAsset || !keepViewed || viewedRevisionId.value == null || !revisions.value.some(r => r.id === viewedRevisionId.value)) {
        viewedRevisionId.value = latest ? latest.id : null
      }
      // else: was pinned to an older revision and still is — leave it, the
      // "Jump to newest" pill covers the gap (onNewest recomputes to false).
    } finally {
      loading.value = false
    }
  }

  async function openOnAsset(id: number, revisionId?: number | null) {
    workspaceFile.value = null
    await syncAsset(id, { keepViewed: assetId.value === id })
    if (revisionId != null && revisions.value.some(r => r.id === revisionId)) {
      viewedRevisionId.value = revisionId
    }
    stageOpen.value = true
    dismissedAssetId.value = null
  }

  // What the header's "show artifact panel" button brings back: the file that
  // was being previewed when the panel closed, else the chat's artifact asset.
  const lastClosedFile = ref<WorkspaceFile | null>(null)

  function close() {
    stageOpen.value = false
    lastClosedFile.value = workspaceFile.value
    workspaceFile.value = null
    dismissedAssetId.value = assetId.value
  }

  function toggle() {
    if (stageOpen.value) close()
    else reopen()
  }

  // Always opens: with the last file, else the chat's artifact, else an empty
  // panel that fills in as soon as the agent produces something.
  function reopen() {
    dismissedAssetId.value = null
    if (lastClosedFile.value) openFile(lastClosedFile.value)
    else if (assetId.value != null) openOnAsset(assetId.value)
    else stageOpen.value = true
  }

  // Chip click: navigates within an open stage, or reopens a closed one.
  function selectFromChip(artifact: ArtifactMeta) {
    workspaceFile.value = null
    if (stageOpen.value && assetId.value === artifact.asset_id) {
      viewedRevisionId.value = artifact.revision_id
      return
    }
    openOnAsset(artifact.asset_id, artifact.revision_id)
  }

  function viewRevision(revisionId: number) {
    viewedRevisionId.value = revisionId
  }

  function jumpToNewest() {
    if (latestRevisionId.value != null) viewedRevisionId.value = latestRevisionId.value
  }

  async function setAsLatest() {
    if (assetId.value == null || viewedRevisionId.value == null || onNewest.value) return
    await assetApi.restoreRevision(assetId.value, viewedRevisionId.value)
    await syncAsset(assetId.value)
    jumpToNewest()
  }

  // Auto-track: whenever the chat's active artifact asset changes, load its
  // revisions so chips can resolve thumbnails/badges even while the panel is
  // closed. Only auto-*opens* the panel if the user hasn't dismissed it.
  watch(latestArtifactAssetId, (id) => {
    if (id == null) return
    if (assetId.value === id) {
      if (!isUserClosed(id)) stageOpen.value = true
      return
    }
    syncAsset(id).then(() => {
      if (!isUserClosed(id)) stageOpen.value = true
    }).catch((err) => {
      console.error('[artifact-stage] failed to load revisions for asset', id, err)
    })
  }, { immediate: true })

  // New revisions of the currently-staged asset arriving over WebSocket:
  // refresh the chain. Revision chains are short, so a full refetch per new
  // item is simpler and cheaper than reconciling WS payloads by hand.
  watch(() => items.value.length, () => {
    const meta = latestArtifactMeta.value
    if (!meta || meta.asset_id == null || meta.asset_id !== assetId.value) return
    if (!revisions.value.some(r => r.id === meta.revision_id)) {
      // On the latest revision → the new one always jumps into view; pinned
      // to an older one → stay put (the Jump to newest pill covers the gap).
      syncAsset(assetId.value, { keepViewed: !onNewest.value })
    }
  })

  // Per-chat persistence of width and panel state; identity reset on chat
  // switch, then the stored state for the new chat is restored. A file that
  // was showing comes straight back; an artifact asset comes back through the
  // auto-open watch above once the chat's items load.
  let restoring = false
  watch(chatId, (id) => {
    restoring = true
    try {
      stageOpen.value = false
      workspaceFile.value = null
      lastClosedFile.value = null
      dismissedAssetId.value = null
      assetId.value = null
      asset.value = null
      revisions.value = []
      viewedRevisionId.value = null
      if (id == null) return
      const stored = localStorage.getItem(widthKey(id))
      if (stored != null) {
        const parsed = Number(stored)
        if (Number.isFinite(parsed)) width.value = Math.min(STAGE_MAX_WIDTH, Math.max(STAGE_MIN_WIDTH, parsed))
      }
      const st = readState(id)
      dismissedAssetId.value = st?.dismissedAssetId ?? null
      if (st?.file) {
        if (st.open) openFile(st.file)
        else lastClosedFile.value = st.file
      } else if (st?.open) {
        stageOpen.value = true
      }
    } finally {
      restoring = false
    }
  }, { immediate: true })

  watch([stageOpen, workspaceFile, lastClosedFile, dismissedAssetId], () => {
    if (restoring || chatId.value == null) return
    const state: PersistedStageState = {
      open: stageOpen.value,
      file: workspaceFile.value ?? lastClosedFile.value,
      dismissedAssetId: dismissedAssetId.value,
    }
    localStorage.setItem(stateKey(chatId.value), JSON.stringify(state))
  }, { flush: 'sync' })

  watch(width, (val) => {
    if (chatId.value != null) localStorage.setItem(widthKey(chatId.value), String(val))
  })

  let stopResize: (() => void) | null = null
  function startResize(e: MouseEvent) {
    e.preventDefault()
    stopResize?.()
    const startX = e.clientX
    const startWidth = width.value
    const prevUserSelect = document.body.style.userSelect
    const prevCursor = document.body.style.cursor
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.getSelection()?.removeAllRanges()
    resizing.value = true

    function onMove(ev: MouseEvent) {
      ev.preventDefault()
      // Handle sits on the chat column's right edge: dragging right widens the chat.
      const delta = ev.clientX - startX
      width.value = Math.min(STAGE_MAX_WIDTH, Math.max(STAGE_MIN_WIDTH, startWidth + delta))
    }
    function onUp() {
      document.body.style.userSelect = prevUserSelect
      document.body.style.cursor = prevCursor
      resizing.value = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      stopResize = null
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    stopResize = onUp
  }

  return {
    stageOpen,
    workspaceFile,
    openFile,
    assetId,
    asset,
    revisions,
    viewedRevisionId,
    viewedRevision,
    latestRevisionId,
    latestArtifactAssetId,
    onNewest,
    loading,
    width,
    resizing,
    findRevision,
    close,
    toggle,
    reopen,
    openOnAsset,
    viewRevision,
    jumpToNewest,
    setAsLatest,
    selectFromChip,
    startResize,
  }
}
