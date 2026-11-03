/**
 * Composable for uploading files to the library.
 *
 * Provides global upload state management for drag-drop uploads
 * with progress tracking displayed in the TopBar.
 */

import { ref, computed, reactive } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { isLibraryUpload } from '../utils/libraryUploadFormats'
import { addToast } from './useToasts'

function getAPIBase() {
  return getApiBase()
}

export interface UploadProgress {
  isUploading: boolean
  total: number
  completed: number
  failed: number
  errors: string[]
}

export interface UploadResult {
  filename: string
  status: 'success' | 'error'
  path?: string
  media_id?: number
  file_hash?: string
  width?: number
  height?: number
  error?: string
}

// Singleton state - shared across all uses
const progress = reactive<UploadProgress>({
  isUploading: false,
  total: 0,
  completed: 0,
  failed: 0,
  errors: [],
})

// Track if we should show the progress (persists briefly after completion)
const showProgress = ref(false)
let hideProgressTimer: ReturnType<typeof setTimeout> | null = null

export function useLibraryUpload() {
  const percentComplete = computed(() => {
    if (progress.total === 0) return 0
    return Math.round(((progress.completed + progress.failed) / progress.total) * 100)
  })

  const statusText = computed(() => {
    if (progress.isUploading) {
      return `Uploading ${progress.completed + progress.failed}/${progress.total}`
    }
    if (progress.total > 0) {
      if (progress.failed > 0) {
        return `${progress.completed} uploaded, ${progress.failed} failed`
      }
      return `${progress.completed} uploaded`
    }
    return ''
  })

  /**
   * Filter files to only include accepted media types.
   */
  function filterMediaFiles(files: File[]): File[] {
    return files.filter(isLibraryUpload)
  }

  /**
   * Upload multiple files to the library.
   *
   * Files are uploaded in batches for efficiency.
   * Progress is tracked in the shared state.
   *
   * @param files - Files to upload
   * @param markerIds - Optional array of marker IDs to apply to uploaded media
   */
  async function uploadFiles(
    files: File[],
    markerIds?: number[],
    projectId?: number | null,
  ): Promise<UploadResult[]> {
    // Filter to media files only
    const mediaFiles = filterMediaFiles(files)
    const rejected = files.filter(file => !isLibraryUpload(file))
    if (rejected.length) {
      const names = rejected.slice(0, 3).map(file => file.name).join(', ')
      addToast(`Skipped ${rejected.length} unsupported ${rejected.length === 1 ? 'file' : 'files'}: ${names}${rejected.length > 3 ? '…' : ''}. Supported: images, videos, audio and SVG.`, 'warning', 8000)
    }

    if (mediaFiles.length === 0) {
      console.log('[LibraryUpload] No valid media files to upload')
      return []
    }

    // Reset progress
    progress.isUploading = true
    progress.total = mediaFiles.length
    progress.completed = 0
    progress.failed = 0
    progress.errors = []
    showProgress.value = true

    // Clear any pending hide timer
    if (hideProgressTimer) {
      clearTimeout(hideProgressTimer)
      hideProgressTimer = null
    }

    const results: UploadResult[] = []
    const BATCH_SIZE = 10

    // Upload in batches
    for (let i = 0; i < mediaFiles.length; i += BATCH_SIZE) {
      const batch = mediaFiles.slice(i, i + BATCH_SIZE)

      try {
        const formData = new FormData()
        batch.forEach(file => {
          formData.append('files', file)
        })

        // Add marker IDs if specified
        if (markerIds && markerIds.length > 0) {
          formData.append('marker_ids', markerIds.join(','))
        }
        if (projectId != null) {
          formData.append('project_id', String(projectId))
        }

        const response = await axios.post(`${getAPIBase()}/generate/upload-bulk`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })

        const batchResults: UploadResult[] = response.data.results
        results.push(...batchResults)

        // Update progress
        for (const result of batchResults) {
          if (result.status === 'success') {
            progress.completed++
          } else {
            progress.failed++
            if (result.error) {
              progress.errors.push(`${result.filename}: ${result.error}`)
            }
          }
        }
      } catch (error: any) {
        // Batch failed entirely
        console.error('[LibraryUpload] Batch upload failed:', error)
        for (const file of batch) {
          progress.failed++
          const errorMsg = error.response?.data?.detail || error.message || 'Upload failed'
          progress.errors.push(`${file.name}: ${errorMsg}`)
          results.push({
            filename: file.name,
            status: 'error',
            error: errorMsg,
          })
        }
      }
    }

    progress.isUploading = false
    // Auto-hide progress after 3 seconds
    hideProgressTimer = setTimeout(() => {
      clearProgress()
    }, 3000)

    return results
  }

  /**
   * Clear the progress state.
   */
  function clearProgress() {
    progress.isUploading = false
    progress.total = 0
    progress.completed = 0
    progress.failed = 0
    progress.errors = []
    showProgress.value = false

    if (hideProgressTimer) {
      clearTimeout(hideProgressTimer)
      hideProgressTimer = null
    }
  }

  return {
    progress,
    showProgress,
    percentComplete,
    statusText,
    uploadFiles,
    clearProgress,
    filterMediaFiles,
  }
}
