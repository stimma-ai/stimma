import axios from 'axios'
import { getCurrentProfileId, getCurrentDbGuid } from './useProfile'
import { getApiBase } from '../apiConfig'
import { useTauriDownload } from './useTauriDownload'
import { useTheme } from './useTheme'

// Use dynamic API base - will be '/api' in dev, 'http://127.0.0.1:PORT/api' in Tauri
function getAPIBase() {
  return getApiBase()
}

export function useMediaApi() {
  async function fetchMedia(params) {
    const response = await axios.get(`${getAPIBase()}/media`, { params })
    return response.data
  }

  async function fetchMediaIds(params) {
    const response = await axios.get(`${getAPIBase()}/media/ids`, { params })
    return response.data
  }

  async function getMediaItem(id, options = {}) {
    const params = {}
    if (options.includeTrashed) {
      params.include_trashed = true
    }
    const response = await axios.get(`${getAPIBase()}/media/${id}`, { params })
    return response.data
  }

  async function findMediaIndex(mediaId, params) {
    const response = await axios.get(`${getAPIBase()}/media/${mediaId}/find-index`, { params })
    return response.data
  }

  async function searchSimilarMedia(mediaId, topK = 100) {
    const response = await axios.post(`${getAPIBase()}/search/similar`, {
      media_id: mediaId,
      top_k: topK
    })
    return response.data
  }

  async function getStats() {
    const response = await axios.get(`${getAPIBase()}/stats`)
    return response.data
  }

  async function getTopKeywords(params = {}) {
    // Support both old style (number) and new style (object)
    const requestParams = typeof params === 'number' ? { limit: params } : params
    const response = await axios.get(`${getAPIBase()}/keywords/top`, {
      params: requestParams
    })
    return response.data
  }

  async function getConfig() {
    const response = await axios.get(`${getAPIBase()}/config`)
    return response.data
  }

  async function getFilterCounts(params = {}) {
    const response = await axios.get(`${getAPIBase()}/filter-counts`, { params })
    return response.data
  }

  // Thumbnail URL version - bump this when thumbnail generation algorithm changes
  // to force browser cache invalidation (v10 = thumbnail mode support)
  const THUMBNAIL_URL_VERSION = 11

  const { resolvedTheme } = useTheme()

  function getThumbnailUrl(fileHashOrMediaId, size = null, options = {}) {
    const dbGuid = getCurrentDbGuid()
    const isMediaId = typeof fileHashOrMediaId === 'number'
    const mode = options.mode || 'crop'

    if (dbGuid) {
      // New db_guid URL format (globally unique, cache-safe)
      const urlParams = new URLSearchParams({ v: THUMBNAIL_URL_VERSION })
      if (size) urlParams.append('size', size)
      if (mode !== 'crop') urlParams.append('mode', mode)
      urlParams.append('theme', resolvedTheme.value)
      const params = `?${urlParams.toString()}`
      if (isMediaId) {
        return `${getAPIBase()}/db/${dbGuid}/media/${fileHashOrMediaId}/thumbnail${params}`
      }
      return `${getAPIBase()}/db/${dbGuid}/thumbnail/${fileHashOrMediaId}${params}`
    }
    // Fallback to old format if db_guid not yet loaded
    const profileId = getCurrentProfileId()
    const urlParams = new URLSearchParams({ profile: profileId, v: THUMBNAIL_URL_VERSION })
    if (size) urlParams.append('size', size)
    if (mode !== 'crop') urlParams.append('mode', mode)
    urlParams.append('theme', resolvedTheme.value)
    if (isMediaId) {
      return `${getAPIBase()}/media/${fileHashOrMediaId}/thumbnail?${urlParams.toString()}`
    }
    return `${getAPIBase()}/thumbnail/${fileHashOrMediaId}?${urlParams.toString()}`
  }

  function getMediaFileUrl(fileHashOrMediaId) {
    const dbGuid = getCurrentDbGuid()
    const isMediaId = typeof fileHashOrMediaId === 'number'

    if (dbGuid) {
      // New db_guid URL format (globally unique, cache-safe)
      if (isMediaId) {
        return `${getAPIBase()}/db/${dbGuid}/media/${fileHashOrMediaId}/file`
      }
      return `${getAPIBase()}/db/${dbGuid}/media/by-hash/${fileHashOrMediaId}/file`
    }
    // Fallback to old format if db_guid not yet loaded
    const profileId = getCurrentProfileId()
    if (isMediaId) {
      return `${getAPIBase()}/media/${fileHashOrMediaId}/file?profile=${profileId}`
    }
    return `${getAPIBase()}/media/by-hash/${fileHashOrMediaId}/file?profile=${profileId}`
  }

  function getMseLoopUrls(fileHash) {
    const dbGuid = getCurrentDbGuid()
    if (dbGuid) {
      const base = `${getAPIBase()}/db/${dbGuid}/media/by-hash/${fileHash}/mse-loop`
      return {
        manifest: base,
        init: `${base}/init`,
        segment: `${base}/segment`,
      }
    }
    const profileId = getCurrentProfileId()
    const base = `${getAPIBase()}/media/by-hash/${fileHash}/mse-loop`
    const query = `?profile=${encodeURIComponent(profileId)}`
    return {
      manifest: `${base}${query}`,
      init: `${base}/init${query}`,
      segment: `${base}/segment${query}`,
    }
  }

  function getProgressStream() {
    return new EventSource(`${getAPIBase()}/progress`)
  }

  // ===== Markers =====
  async function getMarkers() {
    const response = await axios.get(`${getAPIBase()}/markers`)
    return response.data
  }

  async function addMarkerToMedia(mediaId, markerId) {
    const response = await axios.post(`${getAPIBase()}/media/${mediaId}/markers/${markerId}`)
    return response.data
  }

  async function removeMarkerFromMedia(mediaId, markerId) {
    const response = await axios.delete(`${getAPIBase()}/media/${mediaId}/markers/${markerId}`)
    return response.data
  }

  async function bulkMarkerOperation(mediaIds, markerId, add = true) {
    const response = await axios.post(`${getAPIBase()}/media/batch/markers`, {
      media_ids: mediaIds.map(id => parseInt(id)),
      marker_id: parseInt(markerId),
      add
    })
    return response.data
  }

  // ===== Tags =====
  async function getTags(withCounts = false) {
    const params = { with_counts: withCounts }
    const response = await axios.get(`${getAPIBase()}/tags`, { params })
    return response.data
  }

  async function createTag(tagText) {
    const response = await axios.post(`${getAPIBase()}/tags`, { tag_text: tagText })
    return response.data
  }

  async function addTagsToMedia(mediaId, tags) {
    const response = await axios.post(`${getAPIBase()}/media/${mediaId}/tags`, { tags })
    return response.data
  }

  async function removeTagFromMedia(mediaId, tagId) {
    const response = await axios.delete(`${getAPIBase()}/media/${mediaId}/tags/${tagId}`)
    return response.data
  }

  async function bulkTagOperation(mediaIds, tagTexts = [], removeTagIds = []) {
    const payload = {
      media_ids: mediaIds.map(id => parseInt(id)),
      tag_texts: tagTexts
    }

    // Only include remove_tag_ids if there are any
    if (removeTagIds.length > 0) {
      payload.remove_tag_ids = removeTagIds.map(id => parseInt(id))
    }

    console.log('bulkTagOperation payload:', payload)
    const response = await axios.post(`${getAPIBase()}/media/batch/tags`, payload)
    return response.data
  }

  async function deleteTag(tagId) {
    const response = await axios.delete(`${getAPIBase()}/tags/${tagId}`)
    return response.data
  }

  // ===== Boards =====
  async function getBoards(projectId = null) {
    const params = {}
    if (projectId != null) params.project_id = projectId
    const response = await axios.get(`${getAPIBase()}/boards`, { params })
    return response.data
  }

  async function createBoard(name = '', projectId = null) {
    const response = await axios.post(`${getAPIBase()}/boards`, { name, project_id: projectId })
    return response.data
  }

  async function getBoard(boardId) {
    const response = await axios.get(`${getAPIBase()}/boards/${boardId}`)
    return response.data
  }

  async function updateBoard(boardId, updates) {
    const response = await axios.put(`${getAPIBase()}/boards/${boardId}`, updates)
    return response.data
  }

  async function deleteBoard(boardId) {
    const response = await axios.delete(`${getAPIBase()}/boards/${boardId}`)
    return response.data
  }

  async function restoreBoard(boardId) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/restore`)
    return response.data
  }

  async function createBoardSection(boardId, name = null) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/sections`, { name })
    return response.data
  }

  async function updateBoardSection(sectionId, updates) {
    const response = await axios.put(`${getAPIBase()}/boards/sections/${sectionId}`, updates)
    return response.data
  }

  async function deleteBoardSection(sectionId) {
    const response = await axios.delete(`${getAPIBase()}/boards/sections/${sectionId}`)
    return response.data
  }

  async function reorderBoardSections(boardId, sectionIds) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/sections/reorder`, {
      section_ids: sectionIds
    })
    return response.data
  }

  async function addMediaToBoard(boardId, mediaIds, sectionId = null) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/items`, {
      media_ids: mediaIds.map(id => parseInt(id)),
      section_id: sectionId == null ? null : parseInt(sectionId)
    })
    return response.data
  }

  async function removeMediaFromBoardSection(sectionId, mediaId) {
    const response = await axios.delete(`${getAPIBase()}/boards/sections/${sectionId}/items/${mediaId}`)
    return response.data
  }

  async function moveBoardItem(boardId, mediaId, fromSectionId, toSectionId, targetIndex) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/items/move`, {
      media_id: parseInt(mediaId),
      from_section_id: parseInt(fromSectionId),
      to_section_id: parseInt(toSectionId),
      target_index: targetIndex
    })
    return response.data
  }

  async function bulkRemoveFromBoard(boardId, mediaIds) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/items/bulk-remove`, {
      media_ids: mediaIds.map(id => parseInt(id))
    })
    return response.data
  }

  async function bulkMoveBoardItems(boardId, mediaIds, toSectionId) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/items/bulk-move`, {
      media_ids: mediaIds.map(id => parseInt(id)),
      to_section_id: parseInt(toSectionId)
    })
    return response.data
  }

  async function getMediaBoards(mediaId) {
    const response = await axios.get(`${getAPIBase()}/media/${mediaId}/boards`)
    return response.data
  }

  async function duplicateBoard(boardId) {
    const response = await axios.post(`${getAPIBase()}/boards/${boardId}/duplicate`)
    return response.data
  }

  // ===== Projects =====
  async function getProjects() {
    const response = await axios.get(`${getAPIBase()}/projects`)
    return response.data
  }

  async function createProject(name = '') {
    const response = await axios.post(`${getAPIBase()}/projects`, { name })
    return response.data
  }

  async function getProject(projectId) {
    const response = await axios.get(`${getAPIBase()}/projects/${projectId}`)
    return response.data
  }

  async function updateProject(projectId, updates) {
    const response = await axios.put(`${getAPIBase()}/projects/${projectId}`, updates)
    return response.data
  }

  async function deleteProject(projectId) {
    const response = await axios.delete(`${getAPIBase()}/projects/${projectId}`)
    return response.data
  }

  async function addMediaToProject(projectId, mediaIds) {
    const response = await axios.post(`${getAPIBase()}/projects/${projectId}/assets`, {
      media_ids: mediaIds.map(id => parseInt(id))
    })
    return response.data
  }

  async function removeMediaFromProject(projectId, mediaId) {
    const response = await axios.delete(`${getAPIBase()}/projects/${projectId}/assets/${mediaId}`)
    return response.data
  }

  async function getMediaProjects(mediaId) {
    const response = await axios.get(`${getAPIBase()}/media/${mediaId}/projects`)
    return response.data
  }

  // ===== Delete & Trash =====
  async function deleteMedia(mediaId) {
    const response = await axios.delete(`${getAPIBase()}/media/${mediaId}`)
    return response.data
  }

  async function bulkDeleteMedia(mediaIds) {
    const response = await axios.post(`${getAPIBase()}/media/batch/delete`, {
      media_ids: mediaIds.map(id => parseInt(id))
    })
    return response.data
  }

  async function getTrash(params = {}) {
    const response = await axios.get(`${getAPIBase()}/trash`, { params })
    return response.data
  }

  async function getTrashFilterCounts(params = {}) {
    const response = await axios.get(`${getAPIBase()}/trash/filter-counts`, { params })
    return response.data
  }

  async function restoreFromTrash(mediaId) {
    const response = await axios.post(`${getAPIBase()}/trash/${mediaId}/restore`)
    return response.data
  }

  async function permanentlyDeleteMedia(mediaId) {
    const response = await axios.delete(`${getAPIBase()}/trash/${mediaId}`)
    return response.data
  }

  async function emptyTrash() {
    const response = await axios.delete(`${getAPIBase()}/trash`)
    return response.data
  }

  async function getActiveDeleteOperation() {
    const response = await axios.get(`${getAPIBase()}/delete-operations/active`)
    return response.data
  }

  async function getDeleteOperation(operationId) {
    const response = await axios.get(`${getAPIBase()}/delete-operations/${operationId}`)
    return response.data
  }

  async function bulkRestoreFromTrash(mediaIds) {
    const response = await axios.post(`${getAPIBase()}/trash/batch/restore`, {
      media_ids: mediaIds.map(id => parseInt(id))
    })
    return response.data
  }

  async function bulkPermanentlyDelete(mediaIds) {
    const response = await axios.post(`${getAPIBase()}/trash/batch/delete`, {
      media_ids: mediaIds.map(id => parseInt(id))
    })
    return response.data
  }

  // ===== Face Detection =====
  async function getMediaFaces(mediaId) {
    const response = await axios.get(`${getAPIBase()}/media/${mediaId}/faces`)
    return response.data
  }

  // ===== Saved Views =====
  async function getSavedViews() {
    const response = await axios.get(`${getAPIBase()}/saved-views`)
    return response.data
  }

  async function getSavedView(viewId) {
    const response = await axios.get(`${getAPIBase()}/saved-views/${viewId}`)
    return response.data
  }

  async function createSavedView(name, filters, sortBy = 'created_desc') {
    const response = await axios.post(`${getAPIBase()}/saved-views`, {
      name,
      filters,
      sort_by: sortBy
    })
    return response.data
  }

  async function updateSavedView(viewId, updates) {
    // Convert camelCase to snake_case if needed
    const payload = {}
    if (updates.name !== undefined) payload.name = updates.name
    if (updates.filters !== undefined) payload.filters = updates.filters
    if (updates.sortBy !== undefined) payload.sort_by = updates.sortBy

    const response = await axios.put(`${getAPIBase()}/saved-views/${viewId}`, payload)
    return response.data
  }

  async function deleteSavedView(viewId) {
    const response = await axios.delete(`${getAPIBase()}/saved-views/${viewId}`)
    return response.data
  }

  async function reorderSavedView(viewId, direction) {
    const response = await axios.post(`${getAPIBase()}/saved-views/${viewId}/reorder`, { direction })
    return response.data
  }

  // ===== Download =====
  /**
   * Download one or more media files.
   * This is the SINGLE entry point for all downloads in the app.
   * - Single file: downloads directly with original filename
   * - Multiple files: downloads as a zip file
   * Works in both browser and Tauri.
   */
  async function downloadMedia(mediaIds) {
    if (!mediaIds || mediaIds.length === 0) {
      console.warn('[useMediaApi] downloadMedia called with no media IDs')
      return
    }

    const { downloadFromResponse } = useTauriDownload()

    try {
      // Use axios to get the file as a blob
      // The backend returns the file with proper Content-Disposition header
      const response = await axios.post(
        `${getAPIBase()}/media/download`,
        { media_ids: mediaIds.map(id => parseInt(id)) },
        { responseType: 'blob' }
      )

      // Extract filename from Content-Disposition header
      // Axios headers can be accessed via get() method or bracket notation
      const contentDisposition = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
      let filename = 'download'
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="([^"]+)"/)
        if (match) {
          filename = match[1]
        }
      }

      // Use the Tauri-aware download helper (works in both Tauri and browser)
      await downloadFromResponse(response.data, filename)
    } catch (error) {
      console.error('[useMediaApi] Download failed:', error)
      throw error
    }
  }

  /**
   * Create a set (.stimmaset.json) from selected media items.
   * @param {number[]} mediaIds - Array of media IDs to include in the set
   * @param {string} [title] - Optional title for the set
   * @param {number} [projectId] - Project context the set is created in; the set is attached to it
   * @returns {Promise<{file_path: string, title: string, item_count: number}>}
   */
  async function createSetFromMedia(mediaIds, title = null, projectId = null, assetIds = null) {
    const payload = assetIds?.length ? { asset_ids: assetIds } : { media_ids: mediaIds }
    if (title) {
      payload.title = title
    }
    if (projectId) {
      payload.project_id = projectId
    }
    const response = await axios.post(`${getAPIBase()}/media/sets`, payload)
    return response.data
  }

  return {
    fetchMedia,
    fetchMediaIds,
    getMediaItem,
    findMediaIndex,
    searchSimilarMedia,
    getStats,
    getTopKeywords,
    getConfig,
    getFilterCounts,
    getThumbnailUrl,
    getMediaFileUrl,
    getMseLoopUrls,
    getProgressStream,
    // Markers
    getMarkers,
    addMarkerToMedia,
    removeMarkerFromMedia,
    bulkMarkerOperation,
    // Tags
    getTags,
    createTag,
    addTagsToMedia,
    removeTagFromMedia,
    bulkTagOperation,
    deleteTag,
    // Boards
    getBoards,
    getMediaBoards,
    duplicateBoard,
    createBoard,
    getBoard,
    updateBoard,
    deleteBoard,
    restoreBoard,
    createBoardSection,
    updateBoardSection,
    deleteBoardSection,
    reorderBoardSections,
    addMediaToBoard,
    removeMediaFromBoardSection,
    moveBoardItem,
    bulkRemoveFromBoard,
    bulkMoveBoardItems,
    // Projects
    getProjects,
    createProject,
    getProject,
    updateProject,
    deleteProject,
    addMediaToProject,
    removeMediaFromProject,
    getMediaProjects,
    // Delete & Trash
    deleteMedia,
    bulkDeleteMedia,
    getTrash,
    getTrashFilterCounts,
    restoreFromTrash,
    permanentlyDeleteMedia,
    emptyTrash,
    getActiveDeleteOperation,
    getDeleteOperation,
    bulkRestoreFromTrash,
    bulkPermanentlyDelete,
    // Face Detection
    getMediaFaces,
    // Saved Views
    getSavedViews,
    getSavedView,
    createSavedView,
    updateSavedView,
    deleteSavedView,
    reorderSavedView,
    // Download
    downloadMedia,
    // Sets
    createSetFromMedia
  }
}
