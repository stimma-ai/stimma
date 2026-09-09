// Stable request slots are supplied by new progress records. Older chats retain
// their recorded preview order; there is no reliable way to infer request order.
export function progressPreviewTiles(data) {
  if (!Array.isArray(data.preview_slots)) {
    return (data.previews || []).map((mediaId, index) => ({
      key: `${index}`, mediaId, option: index + 1, status: 'completed',
    }))
  }
  return data.preview_slots.flatMap((slot, index) => {
    const status = slot.status === 'pending' && data.status !== 'in_progress'
      ? ({ cancelled: 'cancelled', timed_out: 'timed out', error: 'stopped' }[data.status] || 'empty')
      : slot.status
    return (slot.media_ids.length ? slot.media_ids : [null]).map((mediaId, child) => ({
      key: `${index}:${child}`, mediaId, option: index + 1, status,
    }))
  })
}

export function collectChatMedia(items) {
  const entries = []
  const seen = new Set()
  const add = (id, label = '') => {
    if (!id || seen.has(id)) return
    seen.add(id)
    entries.push({ id, label })
  }
  for (const item of items) {
    let metadata = item.item_metadata || {}
    if (typeof metadata === 'string') {
      try { metadata = JSON.parse(metadata) } catch { metadata = {} }
    }
    const data = metadata.display_data || {}
    if (item.item_type === 'progress_display') {
      for (const tile of progressPreviewTiles(data)) {
        add(tile.mediaId, `${data.title || 'Batch'} · Option ${tile.option}`)
      }
    }
    if (item.item_type === 'media_display') {
      for (const row of data.rows || []) {
        add(row.input?.input_image?.media_id)
        for (const reference of row.input?.ref_images || []) add(reference.media_id)
        if (!row.output?.deleted && row.output?.status !== 'trashed') add(row.output?.media_id)
      }
    }
    if (item.item_type === 'scored_results') {
      for (const result of metadata.scored_data?.items || []) add(result.media_id)
    }
    if (item.item_type === 'analysis_result') add(metadata.analysis_data?.media_id)
    if (item.item_type === 'grid_generation') add(data.grid_media_id)
    if (item.item_type === 'assistant_message') {
      const references = /!\[[^\]]*\]\(media(?:_id=|:)(\d+)\)/g
      for (const match of (item.message_text || '').matchAll(references)) add(Number(match[1]))
    }
  }
  return entries
}
