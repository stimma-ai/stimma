/**
 * What a chat's image collections share: per-item view state (which survives a
 * transcript remount), the one active selection, the composer, and the side
 * panel. Provided by ChatView, read by MediaCollection.
 */
import { computed, reactive, ref, shallowRef, type ComputedRef, type InjectionKey, type Ref, type ShallowRef } from 'vue'
import type { CollectionSize, CollectionView } from '../utils/mediaCollectionLayout'

export interface CollectionViewState {
  view: CollectionView
  size: CollectionSize
  active: number
  expanded: boolean
}

/** What the media menu needs to act on one image or on the current picks. */
export interface CollectionMenuTarget {
  mediaId: number
  assetId?: number
  mediaIds: number[]
  assetIds: number[]
  selectedItems: any[]
  projectId?: number | null
}

export interface ChatMediaCollections {
  viewState(itemId: number, initial: () => CollectionView): CollectionViewState
  selection: {
    owner: Ref<number | null>
    ids: Set<number>
    selecting: ComputedRef<boolean>
    universe: Ref<number[]>
    toggle(owner: number, mediaId: number, universe: number[], range?: boolean): void
    start(owner: number, universe: number[]): void
    selectAll(owner?: number, universe?: number[]): void
    clear(): void
  }
  canAttach: ComputedRef<boolean>
  isAttached(mediaId: number): boolean
  attach(mediaIds: number[]): void
  detach(mediaId: number): void
  attachSelection(): void
  compareSelection(): void
  /** A collection tells the menu what its images are; returns the unregister. */
  registerRows(itemId: number, rows: () => any[]): () => void
  /** The clicked image, or every pick when the clicked image is one of them. */
  menuTarget(itemId: number, mediaId: number): CollectionMenuTarget
  /** Every pick in the selecting collection, or null with nothing picked. */
  selectionMenuTarget(): CollectionMenuTarget | null
  panel: {
    available: boolean
    itemId: Ref<number | null>
    target: ShallowRef<HTMLElement | null>
    open(itemId: number): void
    close(): void
  }
}

export const CHAT_MEDIA_COLLECTIONS: InjectionKey<ChatMediaCollections> = Symbol('chatMediaCollections')

interface Options {
  attachments: Ref<Array<{ media_id?: number }>>
  canAttach: () => boolean
  compare: (leftMediaId: number, rightMediaId: number) => void
  panelAvailable: boolean
  panelItemId: Ref<number | null>
  openPanel: (itemId: number) => void
  closePanel: () => void
  /** The chat's project: the menu's collections, chats and project actions act in it. */
  projectId?: () => number | null | undefined
}

export function useChatMediaCollections(options: Options): ChatMediaCollections {
  const states = new Map<number, CollectionViewState>()
  function viewState(itemId: number, initial: () => CollectionView) {
    if (!states.has(itemId)) states.set(itemId, reactive({ view: initial(), size: 'm', active: 0, expanded: false }))
    return states.get(itemId)!
  }

  const owner = ref<number | null>(null)
  const ids = reactive(new Set<number>())
  const armed = ref(false)
  const universe = ref<number[]>([])
  let lastPick: number | null = null

  function adopt(nextOwner: number, nextUniverse: number[]) {
    if (owner.value !== nextOwner) {
      ids.clear()
      lastPick = null
    }
    owner.value = nextOwner
    universe.value = nextUniverse
  }

  function toggle(nextOwner: number, mediaId: number, nextUniverse: number[], range = false) {
    adopt(nextOwner, nextUniverse)
    const on = !ids.has(mediaId)
    const from = nextUniverse.indexOf(lastPick as number)
    const to = nextUniverse.indexOf(mediaId)
    if (range && from !== -1 && to !== -1) {
      for (const id of nextUniverse.slice(Math.min(from, to), Math.max(from, to) + 1)) on ? ids.add(id) : ids.delete(id)
    } else {
      on ? ids.add(mediaId) : ids.delete(mediaId)
    }
    lastPick = mediaId
  }

  function start(nextOwner: number, nextUniverse: number[]) {
    adopt(nextOwner, nextUniverse)
    armed.value = true
  }

  function selectAll(nextOwner = owner.value as number, nextUniverse = universe.value) {
    adopt(nextOwner, nextUniverse)
    armed.value = true
    nextUniverse.forEach(id => ids.add(id))
  }

  function clear() {
    ids.clear()
    armed.value = false
    owner.value = null
    universe.value = []
    lastPick = null
  }

  const canAttach = computed(options.canAttach)
  const isAttached = (mediaId: number) => options.attachments.value.some(a => a.media_id === mediaId)
  function attach(mediaIds: number[]) {
    if (!canAttach.value) return
    for (const media_id of mediaIds) if (!isAttached(media_id)) options.attachments.value.push({ media_id })
  }
  function detach(mediaId: number) {
    options.attachments.value = options.attachments.value.filter(a => a.media_id !== mediaId)
  }

  // Selection follows collection order, not the order of the clicks.
  const ordered = () => [...new Set(universe.value)].filter(id => ids.has(id))

  const rowSources = new Map<number, () => any[]>()
  function registerRows(itemId: number, rows: () => any[]) {
    rowSources.set(itemId, rows)
    return () => { if (rowSources.get(itemId) === rows) rowSources.delete(itemId) }
  }
  function menuItem(itemId: number, mediaId: number) {
    const row = rowSources.get(itemId)?.().find(candidate => candidate?.output?.media_id === mediaId)
    const output = row?.output
    return {
      ...(output || {}),
      ...(row?.input?.label && !output?.title ? { title: row.input.label } : {}),
      id: mediaId, media_id: mediaId, asset_id: output?.asset_id ?? undefined,
    }
  }
  function targetFor(itemId: number, anchor: number, mediaIds: number[]): CollectionMenuTarget {
    const selectedItems = mediaIds.map(id => menuItem(itemId, id))
    const anchorItem = selectedItems.find(item => item.media_id === anchor) || menuItem(itemId, anchor)
    // Asset actions need every pick's asset; a pick without one (a chat-only
    // working result) keeps the menu on media ids.
    const assetIds = selectedItems.map(item => item.asset_id)
    return {
      mediaId: anchor,
      assetId: anchorItem.asset_id,
      mediaIds,
      assetIds: assetIds.every(id => id != null) ? assetIds as number[] : [],
      selectedItems,
      projectId: options.projectId?.(),
    }
  }
  function menuTarget(itemId: number, mediaId: number) {
    const picks = owner.value === itemId && ids.has(mediaId) ? ordered() : []
    return targetFor(itemId, mediaId, picks.length > 1 ? picks : [mediaId])
  }
  function selectionMenuTarget() {
    const picks = ordered()
    if (owner.value == null || !picks.length) return null
    return targetFor(owner.value, picks[0], picks)
  }

  return {
    viewState,
    selection: {
      owner,
      ids,
      selecting: computed(() => armed.value || ids.size > 0),
      universe,
      toggle,
      start,
      selectAll,
      clear,
    },
    canAttach,
    isAttached,
    attach,
    detach,
    attachSelection() {
      attach(ordered())
      clear()
    },
    registerRows,
    menuTarget,
    selectionMenuTarget,
    compareSelection() {
      const [left, right] = ordered()
      if (left != null && right != null) options.compare(left, right)
    },
    panel: {
      available: options.panelAvailable,
      itemId: options.panelItemId,
      target: shallowRef<HTMLElement | null>(null),
      open: options.openPanel,
      close: options.closePanel,
    },
  }
}
