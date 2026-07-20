import axios from 'axios'
import { getApiBase } from '../apiConfig'
import {
  confirmAssetProjectDeletion,
  confirmAssetProjectDeletions,
  prepareAssetProjectDeletion,
  prepareAssetProjectDeletions,
} from '../utils/editorProjectPrivacy'

export interface AssetBrowserItem {
  asset_id: number
  media_id: number
  revision_id: number
  revision_number: number
  asset_state: 'active' | 'trashed' | 'deleting'
  asset_title?: string | null
  expires_at?: string | null
  file_hash: string
  file_format: string
  [key: string]: unknown
}

export interface AssetBrowseResponse {
  items: AssetBrowserItem[]
  total: number
  page: number
  page_size: number
}

const api = () => getApiBase()

/**
 * Asset identity/organization API. Payload delivery and technical operations
 * deliberately remain in useMediaApi and require an explicit media_id.
 */
export function useAssetApi() {
  async function fetchAssets(params: Record<string, unknown> = {}): Promise<AssetBrowseResponse> {
    return (await axios.get(`${api()}/assets/browse`, { params })).data
  }

  async function fetchAssetIds(params: Record<string, unknown> = {}): Promise<{ ids: number[] }> {
    return (await axios.get(`${api()}/assets/browse/ids`, { params })).data
  }

  async function getAsset(assetId: number) {
    return (await axios.get(`${api()}/assets/${assetId}`)).data
  }

  async function getAssetBrowserItem(assetId: number, includeTrashed = false): Promise<AssetBrowserItem> {
    return (await axios.get(`${api()}/assets/item/${assetId}/browser`, {
      params: { include_trashed: includeTrashed || undefined },
    })).data
  }

  async function getRevisions(assetId: number) {
    return (await axios.get(`${api()}/assets/${assetId}/revisions`)).data
  }

  async function restoreRevision(assetId: number, revisionId: number) {
    return (await axios.post(`${api()}/assets/${assetId}/revisions/${revisionId}/restore`)).data
  }

  async function getDeletionPreview(assetId: number) {
    return (await axios.get(`${api()}/assets/${assetId}/deletion-preview`)).data
  }

  async function getContextualMedia(params: Record<string, unknown> = {}) {
    return (await axios.get(`${api()}/assets/contextual-media`, { params })).data
  }

  async function promoteContextualMedia(mediaId: number) {
    return (await axios.post(`${api()}/assets/contextual-media/${mediaId}/promote`)).data
  }

  async function getTags(withCounts = false) {
    return (await axios.get(`${api()}/assets/tags`, {
      params: { with_counts: withCounts },
    })).data
  }

  async function getTopKeywords(params: Record<string, unknown> = {}) {
    return (await axios.get(`${api()}/assets/keywords/top`, { params })).data
  }

  async function getFilterCounts(params: Record<string, unknown> = {}) {
    return (await axios.get(`${api()}/assets/filter-counts`, { params })).data
  }

  async function findAssetIndex(assetId: number, params: Record<string, unknown> = {}) {
    const { ids } = await fetchAssetIds(params)
    const index = ids.indexOf(assetId)
    if (index < 0) throw new Error(`Asset ${assetId} is not in this view`)
    return { asset_id: assetId, index, total: ids.length }
  }

  async function addMarker(assetId: number, markerId: number) {
    return (await axios.post(`${api()}/assets/item/${assetId}/markers/${markerId}`)).data
  }

  async function removeMarker(assetId: number, markerId: number) {
    return (await axios.delete(`${api()}/assets/item/${assetId}/markers/${markerId}`)).data
  }

  async function bulkMarker(assetIds: number[], markerId: number, add = true) {
    return (await axios.post(`${api()}/assets/batch/markers`, {
      asset_ids: assetIds,
      marker_id: markerId,
      add,
    })).data
  }

  async function addTags(assetId: number, tags: string[]) {
    return (await axios.post(`${api()}/assets/item/${assetId}/tags`, { tags })).data
  }

  async function removeTag(assetId: number, tagId: number) {
    return (await axios.delete(`${api()}/assets/item/${assetId}/tags/${tagId}`)).data
  }

  async function bulkTags(assetIds: number[], tagTexts: string[] = [], removeTagIds: number[] = []) {
    return (await axios.post(`${api()}/assets/batch/tags`, {
      asset_ids: assetIds,
      tag_texts: tagTexts,
      remove_tag_ids: removeTagIds,
    })).data
  }

  async function addToProject(projectId: number, assetIds: number[]) {
    return (await axios.post(`${api()}/assets/batch/projects/${projectId}`, {
      asset_ids: assetIds,
    })).data
  }

  async function removeFromProject(assetId: number, projectId: number) {
    return (await axios.delete(`${api()}/assets/item/${assetId}/projects/${projectId}`)).data
  }

  async function getProjects(assetId: number) {
    return (await axios.get(`${api()}/assets/item/${assetId}/projects`)).data
  }

  async function getBoards(assetId: number) {
    return (await axios.get(`${api()}/assets/item/${assetId}/boards`)).data
  }

  async function getContainers(assetId: number) {
    return (await axios.get(`${api()}/assets/item/${assetId}/containers`)).data
  }

  async function promoteContainerMembers(assetId: number) {
    return (await axios.post(`${api()}/assets/item/${assetId}/container-members/promote`)).data
  }

  async function trash(assetId: number) {
    return (await axios.delete(`${api()}/assets/${assetId}`)).data
  }

  async function trashMany(assetIds: number[]) {
    return (await axios.post(`${api()}/assets/batch/trash`, { asset_ids: assetIds })).data
  }

  async function restore(assetId: number) {
    return (await axios.post(`${api()}/assets/${assetId}/restore`)).data
  }

  async function restoreMany(assetIds: number[]) {
    return (await axios.post(`${api()}/assets/batch/restore`, { asset_ids: assetIds })).data
  }

  async function permanentlyDelete(assetId: number) {
    const revisions = (await axios.get(`${api()}/assets/${assetId}/revisions`)).data
    prepareAssetProjectDeletion(
      assetId,
      (revisions.items || []).map((revision: { primary_media_id: number }) => revision.primary_media_id),
    )
    const result = (await axios.delete(`${api()}/assets/${assetId}/permanent`)).data
    void confirmAssetProjectDeletion(assetId)
    return result
  }

  async function permanentlyDeleteMany(assetIds: number[]) {
    const uniqueAssetIds = [...new Set(assetIds)]
    const manifest = (await axios.post(`${api()}/assets/batch/deletion-manifest`, {
      asset_ids: uniqueAssetIds,
    })).data
    prepareAssetProjectDeletions((manifest.items || []).map(
      (item: { asset_id: number; media_ids: number[] }) => ({
        assetId: item.asset_id,
        mediaIds: item.media_ids || [],
      }),
    ))

    // Submit the selection in one request; the global deletion queue reports
    // progress in Asset units regardless of how deletion was triggered.
    const result = (await axios.post(`${api()}/assets/batch/permanent`, {
      asset_ids: uniqueAssetIds,
    })).data

    void confirmAssetProjectDeletions(uniqueAssetIds)
    return result
  }

  async function getTrashSourceFileCount(): Promise<{ count: number }> {
    return (await axios.get(`${api()}/trash/source-file-count`)).data
  }

  async function emptyTrash() {
    const manifest = (await axios.get(`${api()}/assets/trash-deletion-manifest`)).data
    prepareAssetProjectDeletions((manifest.items || []).map(
      (item: { asset_id: number; media_ids: number[] }) => ({
        assetId: item.asset_id,
        mediaIds: item.media_ids || [],
      }),
    ))

    // Queue the whole Trash in one request rather than one request per Asset.
    const result = (await axios.delete(`${api()}/assets`)).data

    void confirmAssetProjectDeletions(
      (manifest.items || []).map((item: { asset_id: number }) => item.asset_id),
    )
    return {
      ...result,
      asset_ids: (manifest.items || []).map(
        (item: { asset_id: number }) => item.asset_id,
      ),
    }
  }

  async function addToBoard(boardId: number, assetIds: number[], sectionId: number | null = null) {
    return (await axios.post(`${api()}/boards/${boardId}/items`, {
      asset_ids: assetIds,
      section_id: sectionId,
    })).data
  }

  async function removeFromBoardSection(sectionId: number, assetId: number) {
    return (await axios.delete(`${api()}/boards/sections/${sectionId}/asset-items/${assetId}`)).data
  }

  async function bulkRemoveFromBoard(boardId: number, assetIds: number[]) {
    return (await axios.post(`${api()}/boards/${boardId}/items/bulk-remove`, {
      asset_ids: assetIds,
    })).data
  }

  async function moveBoardItem(
    boardId: number,
    assetId: number,
    fromSectionId: number,
    toSectionId: number,
    targetIndex: number,
  ) {
    return (await axios.post(`${api()}/boards/${boardId}/asset-items/move`, {
      asset_id: assetId,
      from_section_id: fromSectionId,
      to_section_id: toSectionId,
      target_index: targetIndex,
    })).data
  }

  async function bulkMoveBoardItems(boardId: number, assetIds: number[], toSectionId: number) {
    return (await axios.post(`${api()}/boards/${boardId}/items/bulk-move`, {
      asset_ids: assetIds,
      to_section_id: toSectionId,
    })).data
  }

  return {
    fetchAssets,
    fetchAssetIds,
    getAsset,
    getAssetBrowserItem,
    getRevisions,
    restoreRevision,
    getDeletionPreview,
    getContextualMedia,
    promoteContextualMedia,
    getTags,
    getTopKeywords,
    getFilterCounts,
    findAssetIndex,
    addMarker,
    removeMarker,
    bulkMarker,
    addTags,
    removeTag,
    bulkTags,
    addToProject,
    removeFromProject,
    getProjects,
    getBoards,
    getContainers,
    promoteContainerMembers,
    trash,
    trashMany,
    restore,
    restoreMany,
    permanentlyDelete,
    permanentlyDeleteMany,
    emptyTrash,
    getTrashSourceFileCount,
    addToBoard,
    removeFromBoardSection,
    bulkRemoveFromBoard,
    moveBoardItem,
    bulkMoveBoardItems,
  }
}
