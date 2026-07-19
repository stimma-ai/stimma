export function createLatestRequestGate() {
  let latestRequestId = 0

  return {
    begin() {
      latestRequestId += 1
      return latestRequestId
    },
    isCurrent(requestId) {
      return requestId === latestRequestId
    },
    invalidate() {
      latestRequestId += 1
    },
  }
}

export function getFilterCountWatchValues(filters = {}, {
  similarSearchActive = false,
  similarSearchSourceItems = [],
} = {}) {
  return [
    filters.captionQuery,
    filters.promptQuery,
    filters.similarToText,
    filters.mediaTypes,
    filters.excludedMediaTypes,
    filters.resolutions,
    filters.excludedResolutions,
    filters.selectedKeywords,
    filters.excludedKeywords,
    filters.selectedFolders,
    filters.excludedFolders,
    filters.selectedTags,
    filters.excludedTags,
    filters.selectedProjects,
    filters.excludedProjects,
    filters.projectMembership,
    filters.selectedTools,
    filters.excludedTools,
    filters.selectedMarkers,
    filters.excludedMarkers,
    filters.isImported,
    filters.isUnused,
    filters.showExpiring,
    filters.excludeExpiring,
    filters.createdAfter,
    filters.createdBefore,
    similarSearchActive,
    filters.similarTo,
    filters.similarFaceTo,
    similarSearchSourceItems,
  ]
}

export function buildFilterCountParams(filters = {}, {
  isTrashMode = false,
  similarSearchActive = false,
  similarSearchSourceItems = [],
} = {}) {
  const params = {
    keyword_limit: 50,
    state: isTrashMode ? 'trashed' : 'active',
  }

  const setText = (key, value, { trim = false } = {}) => {
    if (typeof value !== 'string' || !value) return
    const nextValue = trim ? value.trim() : value
    if (nextValue) params[key] = nextValue
  }
  const setList = (key, value) => {
    if (Array.isArray(value) && value.length > 0) params[key] = value.join(',')
  }

  setText('caption_query', filters.captionQuery)
  setText('prompt_query', filters.promptQuery)
  setText('similar_to_text', filters.similarToText, { trim: true })
  setList('media_types', filters.mediaTypes)
  setList('excluded_media_types', filters.excludedMediaTypes)
  setList('resolutions', filters.resolutions)
  setList('excluded_resolutions', filters.excludedResolutions)
  setList('keywords', filters.selectedKeywords)
  setList('excluded_keywords', filters.excludedKeywords)
  setList('folders', filters.selectedFolders)
  setList('excluded_folders', filters.excludedFolders)
  setList('tag_ids', filters.selectedTags)
  setList('excluded_tag_ids', filters.excludedTags)
  setList('project_ids', filters.selectedProjects)
  setList('excluded_project_ids', filters.excludedProjects)
  setList('tool_ids', filters.selectedTools)
  setList('excluded_tool_ids', filters.excludedTools)
  setList('marker_ids', filters.selectedMarkers)
  setList('excluded_marker_ids', filters.excludedMarkers)

  if (filters.projectMembership === 'any') params.has_project = true
  else if (filters.projectMembership === 'none') params.has_project = false

  if (filters.isImported !== null && filters.isImported !== undefined) {
    params.is_imported = filters.isImported
  }
  if (filters.isUnused !== null && filters.isUnused !== undefined) {
    params.is_unused = filters.isUnused
  }
  if (filters.showExpiring) params.show_expiring = true
  if (filters.excludeExpiring) params.exclude_expiring = true
  setText('created_after', filters.createdAfter)
  setText('created_before', filters.createdBefore)

  if (similarSearchActive) {
    if (Array.isArray(filters.similarFaceTo) && filters.similarFaceTo.length > 0) {
      params.similar_face_to = filters.similarFaceTo.join(',')
    } else if (Array.isArray(filters.similarTo) && filters.similarTo.length > 0) {
      params.similar_to = filters.similarTo.join(',')
    } else if (similarSearchSourceItems.length > 0) {
      params.similar_to = similarSearchSourceItems
        .map(item => item.media_id || item.id)
        .filter(Boolean)
        .join(',')
    }
  }

  return params
}
