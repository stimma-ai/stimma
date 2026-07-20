import { watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { makeProfileKey } from '../utils/storageKeys'

/**
 * Composable for managing state in URL query parameters and localStorage
 * Supports compact encoding for bookmarkable URLs
 */
export function useUrlState() {
  const router = useRouter()
  const route = useRoute()

  // Storage key for filters (profile-scoped)
  function getFiltersKey() {
    return makeProfileKey('browse', 'url_filters')
  }

  /**
   * Encode filters to compact URL format
   * Format: uses short keys to minimize URL length
   * - cq: caption query
   * - pq: prompt query
   * - stt: similar to text (text-based CLIP search)
   * - mt: media types (i=images, v=videos)
   * - xmt: excluded media types
   * - r: resolutions (s=small, m=medium, l=large)
   * - xr: excluded resolutions
   * - s: sort by (cd=created_desc, ca=created_asc, ri=indexed_desc, r=random, sim=similarity)
   * - k: keywords (comma-separated)
   * - xk: excluded keywords
   * - f: folders (comma-separated)
   * - xf: excluded folders
   * - sim: similar to (media ID)
   * - fsim: similar faces to (media ID)
   * - st: similarity threshold (0.0-1.0)
   * - i: current image index (for slideshow)
   * - ss: slideshow active (1=true)
   */
  function encodeFiltersToUrl(filters, slideshowState = null) {
    const params = new URLSearchParams()

    // Text queries
    if (filters.captionQuery) params.set('cq', filters.captionQuery)
    if (filters.promptQuery) params.set('pq', filters.promptQuery)
    if (filters.similarToText) params.set('stt', filters.similarToText)

    // Media types - compact encoding
    if (filters.mediaTypes?.length > 0) {
      const compact = filters.mediaTypes.map(t => t === 'images' ? 'i' : 'v').join(',')
      params.set('mt', compact)
    }
    if (filters.excludedMediaTypes?.length > 0) {
      const compact = filters.excludedMediaTypes.map(t => t === 'images' ? 'i' : 'v').join(',')
      params.set('xmt', compact)
    }

    // Resolutions - compact encoding
    if (filters.resolutions?.length > 0) {
      const compact = filters.resolutions.map(r => r[0]).join(',') // s, m, l
      params.set('r', compact)
    }
    if (filters.excludedResolutions?.length > 0) {
      const compact = filters.excludedResolutions.map(r => r[0]).join(',')
      params.set('xr', compact)
    }

    // Sort - compact encoding
    if (filters.sortBy && filters.sortBy !== 'created_desc') {
      const sortMap = { created_asc: 'ca', indexed_desc: 'ri', random: 'r', created_desc: 'cd', similarity: 'sim' }
      params.set('s', sortMap[filters.sortBy] || filters.sortBy)
    }

    // Keywords
    if (filters.selectedKeywords?.length > 0) {
      params.set('k', filters.selectedKeywords.join(','))
    }
    if (filters.excludedKeywords?.length > 0) {
      params.set('xk', filters.excludedKeywords.join(','))
    }

    // Projects (membership filter, by id)
    if (filters.selectedProjects?.length > 0) {
      params.set('prj', filters.selectedProjects.join(','))
    }
    if (filters.excludedProjects?.length > 0) {
      params.set('xprj', filters.excludedProjects.join(','))
    }

    // Folders (use base64 to handle special chars in paths)
    if (filters.selectedFolders?.length > 0) {
      params.set('f', btoa(filters.selectedFolders.join('|')))
    }
    if (filters.excludedFolders?.length > 0) {
      params.set('xf', btoa(filters.excludedFolders.join('|')))
    }

    // Tools (comma-separated full_tool_ids)
    if (filters.selectedTools?.length > 0) {
      params.set('tl', filters.selectedTools.join(','))
    }
    if (filters.excludedTools?.length > 0) {
      params.set('xtl', filters.excludedTools.join(','))
    }

    // Imported lineage provenance (1 = imported, 0 = has tool history)
    if (filters.isImported !== null && filters.isImported !== undefined) {
      params.set('imp', filters.isImported ? '1' : '0')
    }

    // Unused / dead-end filter (1 = unused only, 0 = used only)
    if (filters.isUnused !== null && filters.isUnused !== undefined) {
      params.set('unu', filters.isUnused ? '1' : '0')
    }

    // Similar search (supports multiple IDs)
    if (filters.similarTo && filters.similarTo.length > 0) {
      params.set('sim', Array.isArray(filters.similarTo) ? filters.similarTo.join(',') : filters.similarTo)
    }
    if (filters.similarFaceTo && filters.similarFaceTo.length > 0) {
      params.set('fsim', Array.isArray(filters.similarFaceTo) ? filters.similarFaceTo.join(',') : filters.similarFaceTo)
    }

    // Similarity threshold (only encode if not default 0.75)
    if (filters.similarityThreshold !== undefined && filters.similarityThreshold !== 0.75) {
      params.set('st', filters.similarityThreshold)
    }

    // Random seed (for random sort stability)
    if (filters.sortBy === 'random' && slideshowState?.randomSeed !== undefined) {
      params.set('rs', slideshowState.randomSeed)
    }

    // Slideshow state (only add if active)
    if (slideshowState && slideshowState.active) {
      params.set('ss', '1')
      if (slideshowState.index !== undefined && slideshowState.index !== null) {
        params.set('i', slideshowState.index)
      }
      // Slideshow randomization
      if (slideshowState.slideshowRandomized) {
        params.set('ssr', '1')  // slideshow randomized
        if (slideshowState.slideshowRandomSeed) {
          params.set('ssrs', slideshowState.slideshowRandomSeed)  // slideshow random seed
        }
      }
    }

    return params.toString()
  }

  /**
   * Decode filters from URL query parameters
   */
  function decodeFiltersFromUrl(queryParams) {
    const filters = {
      captionQuery: queryParams.cq || '',
      promptQuery: queryParams.pq || '',
      similarToText: queryParams.stt || '',
      mediaTypes: [],
      excludedMediaTypes: [],
      resolutions: [],
      excludedResolutions: [],
      sortBy: 'created_desc',
      selectedKeywords: [],
      excludedKeywords: [],
      selectedFolders: [],
      excludedFolders: [],
      similarTo: [],
      similarFaceTo: [],
      similarityThreshold: 0.75
    }

    if (queryParams.imp === '1') filters.isImported = true
    else if (queryParams.imp === '0') filters.isImported = false

    if (queryParams.unu === '1') filters.isUnused = true
    else if (queryParams.unu === '0') filters.isUnused = false

    // Media types
    if (queryParams.mt) {
      filters.mediaTypes = queryParams.mt.split(',').map(t => t === 'i' ? 'images' : 'videos')
    }
    // Projects
    if (queryParams.prj) {
      filters.selectedProjects = queryParams.prj.split(',').map(Number).filter(Number.isFinite)
    }
    if (queryParams.xprj) {
      filters.excludedProjects = queryParams.xprj.split(',').map(Number).filter(Number.isFinite)
    }

    if (queryParams.xmt) {
      filters.excludedMediaTypes = queryParams.xmt.split(',').map(t => t === 'i' ? 'images' : 'videos')
    }

    // Resolutions
    if (queryParams.r) {
      filters.resolutions = queryParams.r.split(',').map(r => {
        const map = { s: 'small', m: 'medium', l: 'large', h: 'huge' }
        return map[r] || r
      })
    }
    if (queryParams.xr) {
      filters.excludedResolutions = queryParams.xr.split(',').map(r => {
        const map = { s: 'small', m: 'medium', l: 'large', h: 'huge' }
        return map[r] || r
      })
    }

    // Sort
    if (queryParams.s) {
      const sortMap = { ca: 'created_asc', ri: 'indexed_desc', r: 'random', cd: 'created_desc', sim: 'similarity' }
      filters.sortBy = sortMap[queryParams.s] || queryParams.s
    }

    // Keywords
    if (queryParams.k) {
      filters.selectedKeywords = queryParams.k.split(',').filter(k => k)
    }
    if (queryParams.xk) {
      filters.excludedKeywords = queryParams.xk.split(',').filter(k => k)
    }

    // Folders (decode from base64)
    if (queryParams.f) {
      try {
        filters.selectedFolders = atob(queryParams.f).split('|').filter(f => f)
      } catch (e) {
        console.error('Failed to decode folders:', e)
      }
    }
    if (queryParams.xf) {
      try {
        filters.excludedFolders = atob(queryParams.xf).split('|').filter(f => f)
      } catch (e) {
        console.error('Failed to decode excluded folders:', e)
      }
    }

    // Tools
    if (queryParams.tl) {
      filters.selectedTools = queryParams.tl.split(',').filter(t => t)
    }
    if (queryParams.xtl) {
      filters.excludedTools = queryParams.xtl.split(',').filter(t => t)
    }

    // Similar search (supports multiple comma-separated IDs)
    if (queryParams.sim) {
      const ids = queryParams.sim.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id))
      filters.similarTo = ids.length > 0 ? ids : []
    } else {
      filters.similarTo = []
    }

    // Face similarity search (supports multiple comma-separated IDs)
    if (queryParams.fsim) {
      const ids = queryParams.fsim.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id))
      filters.similarFaceTo = ids.length > 0 ? ids : []
      if (filters.similarFaceTo.length > 0) {
        filters.similarTo = []
      }
    } else {
      filters.similarFaceTo = []
    }

    // Similarity threshold
    if (queryParams.st !== undefined) {
      const threshold = parseFloat(queryParams.st)
      if (!isNaN(threshold) && threshold >= 0 && threshold <= 1) {
        filters.similarityThreshold = threshold
      }
    }

    return filters
  }

  /**
   * Decode slideshow state from URL
   */
  function decodeSlideshowFromUrl(queryParams) {
    return {
      active: queryParams.ss === '1',
      index: queryParams.i ? parseInt(queryParams.i) : 0,
      randomized: queryParams.ssr === '1',
      randomSeed: queryParams.ssrs ? parseInt(queryParams.ssrs) : null
    }
  }

  /**
   * Update URL without triggering navigation
   */
  function updateUrl(filters, slideshowState = null) {
    const queryString = encodeFiltersToUrl(filters, slideshowState)
    const newUrl = queryString ? `/?${queryString}` : '/'

    console.log('updateUrl called, slideshowState:', slideshowState, 'newUrl:', newUrl)

    // Use replaceState to avoid adding to history
    if (window.location.pathname + window.location.search !== newUrl) {
      router.replace(newUrl)
    }
  }

  /**
   * Save filters to localStorage
   */
  function saveToLocalStorage(filters) {
    try {
      localStorage.setItem(getFiltersKey(), JSON.stringify(filters))
    } catch (e) {
      console.error('Failed to save filters to localStorage:', e)
    }
  }

  /**
   * Load filters from localStorage
   */
  function loadFromLocalStorage() {
    try {
      const saved = localStorage.getItem(makeProfileKey('browse', 'url_filters'))
      return saved ? JSON.parse(saved) : null
    } catch (e) {
      console.error('Failed to load filters from localStorage:', e)
      return null
    }
  }

  /**
   * Initialize filters from URL or localStorage
   * Priority: URL > localStorage > defaults
   */
  function initializeFilters(defaultFilters) {
    // Check URL first
    const urlFilters = decodeFiltersFromUrl(route.query)
    const hasUrlParams = Object.keys(route.query).length > 0

    if (hasUrlParams) {
      // URL takes precedence
      return urlFilters
    }

    // Fall back to localStorage
    const savedFilters = loadFromLocalStorage()
    if (savedFilters) {
      return { ...defaultFilters, ...savedFilters }
    }

    return defaultFilters
  }

  /**
   * Setup watchers for automatic state persistence
   */
  function setupPersistence(filters, slideshowState = null) {
    // Watch filters and update URL + localStorage
    watch(
      () => ({ ...filters }),
      (newFilters) => {
        updateUrl(newFilters, slideshowState?.value)
        saveToLocalStorage(newFilters)
      },
      { deep: true }
    )

    // Watch slideshow state if provided
    if (slideshowState) {
      watch(
        slideshowState,
        () => {
          updateUrl(filters, slideshowState.value)
        },
        { deep: true }
      )
    }
  }

  return {
    encodeFiltersToUrl,
    decodeFiltersFromUrl,
    decodeSlideshowFromUrl,
    updateUrl,
    saveToLocalStorage,
    loadFromLocalStorage,
    initializeFilters,
    setupPersistence
  }
}
