import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface AssetBrowserItem {
  asset_id: number
  media_id: number
  revision_id: number
  revision_number: number
  asset_state: 'active' | 'trashed' | 'deleting'
  asset_title?: string | null
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
    return (await axios.delete(`${api()}/assets/${assetId}/permanent`)).data
  }

  return {
    fetchAssets,
    fetchAssetIds,
    getAsset,
    addMarker,
    removeMarker,
    bulkMarker,
    addTags,
    removeTag,
    bulkTags,
    addToProject,
    removeFromProject,
    trash,
    trashMany,
    restore,
    restoreMany,
    permanentlyDelete,
  }
}
