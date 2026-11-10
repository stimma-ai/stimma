/**
 * Live shelf entries for the sidebar: open editors as thumbnails instead of
 * named rows. Editor tabs only — every other tab type stays a text row,
 * because chats, tools and collections do have names worth reading.
 *
 * The ordering and capacity rules are pure; see utils/editorShelf.ts.
 */
import { computed, type Ref } from 'vue'
import { editorAssetId, type WorkspaceTab } from './useWorkspaceTabs'
import { isEditorDirty, dirtyEditorAssets } from '../imageEditor/stack/editorDirtyState'
import { rankShelfEntries, type ShelfEntry } from '../utils/editorShelf'

export function useEditorShelf(tabs: Ref<readonly WorkspaceTab[]>) {
  const entries = computed<ShelfEntry[]>(() => {
    // Read the dirty set so ranking recomputes when a stack goes dirty.
    void dirtyEditorAssets.value
    const out: ShelfEntry[] = []
    for (const tab of tabs.value) {
      if (tab.type !== 'editor') continue
      const assetId = editorAssetId(tab)
      if (!assetId) continue
      out.push({
        tabId: tab.id,
        assetId,
        mediaId: tab.editorMediaId,
        displayName: tab.displayName,
        pinned: tab.pinned,
        unsaved: isEditorDirty(assetId),
        touchedAt: tab.lastActivatedAt ?? tab.displayOrder,
        createdOrder: tab.displayOrder,
      })
    }
    return out
  })

  const ranked = computed(() => rankShelfEntries(entries.value))

  return { entries, ranked }
}
