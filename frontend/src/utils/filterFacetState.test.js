import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildFilterCountParams,
  createLatestRequestGate,
  getFilterCountWatchValues,
} from './filterFacetState.js'

test('filter-count params include every All Assets filter that changes availability', () => {
  const params = buildFilterCountParams({
    captionQuery: 'caption',
    promptQuery: 'prompt',
    similarToText: 'red fox',
    mediaTypes: ['images'],
    excludedMediaTypes: ['video'],
    resolutions: ['large'],
    excludedResolutions: ['small'],
    selectedKeywords: ['animal'],
    excludedKeywords: ['indoor'],
    selectedFolders: ['/photos'],
    excludedFolders: ['/drafts'],
    selectedTags: [1],
    excludedTags: [2],
    selectedProjects: [3],
    excludedProjects: [4],
    projectMembership: 'any',
    selectedTools: ['provider:tool'],
    excludedTools: ['provider:old-tool'],
    selectedMarkers: [5],
    excludedMarkers: [6],
    isImported: false,
    isUnused: true,
    showExpiring: true,
    excludeExpiring: true,
    createdAfter: '2026-07-01T00:00:00Z',
    createdBefore: '2026-07-20T00:00:00Z',
  })

  assert.deepEqual(params, {
    keyword_limit: 50,
    state: 'active',
    caption_query: 'caption',
    prompt_query: 'prompt',
    similar_to_text: 'red fox',
    media_types: 'images',
    excluded_media_types: 'video',
    resolutions: 'large',
    excluded_resolutions: 'small',
    keywords: 'animal',
    excluded_keywords: 'indoor',
    folders: '/photos',
    excluded_folders: '/drafts',
    tag_ids: '1',
    excluded_tag_ids: '2',
    project_ids: '3',
    excluded_project_ids: '4',
    tool_ids: 'provider:tool',
    excluded_tool_ids: 'provider:old-tool',
    marker_ids: '5',
    excluded_marker_ids: '6',
    has_project: true,
    is_imported: false,
    is_unused: true,
    show_expiring: true,
    exclude_expiring: true,
    created_after: '2026-07-01T00:00:00Z',
    created_before: '2026-07-20T00:00:00Z',
  })
})

test('latest-request gate rejects stale facet responses', () => {
  const gate = createLatestRequestGate()
  const restrictiveRequest = gate.begin()
  const broadRequest = gate.begin()

  assert.equal(gate.isCurrent(restrictiveRequest), false)
  assert.equal(gate.isCurrent(broadRequest), true)

  gate.invalidate()
  assert.equal(gate.isCurrent(broadRequest), false)
})

test('count refresh dependencies include the formerly sticky filters', () => {
  const values = getFilterCountWatchValues({
    similarToText: 'text-search',
    showExpiring: 'show-expiring',
    excludeExpiring: 'exclude-expiring',
    createdAfter: 'created-after',
    createdBefore: 'created-before',
  })

  for (const value of [
    'text-search',
    'show-expiring',
    'exclude-expiring',
    'created-after',
    'created-before',
  ]) {
    assert.equal(values.includes(value), true)
  }
})

test('similarity inputs use the active search source without dropping text search', () => {
  assert.deepEqual(buildFilterCountParams({
    similarToText: 'landscape',
    similarFaceTo: [8, 9],
    similarTo: [10],
  }, { similarSearchActive: true }), {
    keyword_limit: 50,
    state: 'active',
    similar_to_text: 'landscape',
    similar_face_to: '8,9',
  })
})
