import { EXPIRING_MARKER_ID } from './implicitMarkers.js'

export const DEFAULT_BROWSE_FILTERS = {
  captionQuery: '',
  promptQuery: '',
  mediaTypes: [],
  excludedMediaTypes: [],
  resolutions: [],
  excludedResolutions: [],
  sortBy: 'created_desc',
  selectedKeywords: [],
  excludedKeywords: [],
  selectedFolders: [],
  excludedFolders: [],
  selectedTags: [],
  excludedTags: [],
  selectedProjects: [],
  excludedProjects: [],
  projectMembership: null,   // null = no constraint, 'any' = in any project, 'none' = in no project
  includeProjects: false,    // top level only: false = unfiled assets, true = include project assets
  selectedTools: [],
  excludedTools: [],
  selectedMarkers: [],
  excludedMarkers: [],
  isImported: null,
  isUnused: null,
  similarTo: [],
  similarFaceTo: [],
  similarToText: '',
  similarityThreshold: 0.75,
  createdAfter: null,
  createdBefore: null
}

export function cloneDefaultBrowseFilters() {
  return JSON.parse(JSON.stringify(DEFAULT_BROWSE_FILTERS))
}

export function normalizeBrowseFilters(filters = {}) {
  const normalized = cloneDefaultBrowseFilters()

  for (const key of Object.keys(DEFAULT_BROWSE_FILTERS)) {
    const value = filters[key]
    if (value === undefined) continue

    if (Array.isArray(DEFAULT_BROWSE_FILTERS[key])) {
      normalized[key] = Array.isArray(value) ? [...value] : []
      continue
    }

    normalized[key] = value
  }

  // Expiring used to be its own filter; it is now the implicit:expiring
  // marker. Saved views written before that keep working.
  const addMarker = (key, id) => {
    if (!normalized[key].includes(id)) normalized[key].push(id)
  }
  if (filters.showExpiring) addMarker('selectedMarkers', EXPIRING_MARKER_ID)
  if (filters.excludeExpiring) addMarker('excludedMarkers', EXPIRING_MARKER_ID)

  return normalized
}
