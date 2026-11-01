import { marked } from 'marked'

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
      ? ({ cancelled: 'cancelled', timed_out: 'timed out', interrupted: 'stopped', error: 'stopped' }[data.status] || 'empty')
      : slot.status
    return (slot.media_ids.length ? slot.media_ids : [null]).map((mediaId, child) => ({
      key: `${index}:${child}`, mediaId, option: index + 1, status,
    }))
  })
}

export function collectChatMedia(items) {
  const entries = []
  // Identity belongs to an appearance, not the underlying media. Slot paths
  // remain stable when a pending progress slot fills or older chat items load.
  for (const [index, item] of items.entries()) {
    const itemId = item.id ?? index
    const add = (id, slot, label = '') => {
      if (!id) return
      entries.push({ id, itemId, slot, key: `${itemId}:${slot}:${id}`, label })
    }
    let metadata = item.item_metadata || {}
    if (typeof metadata === 'string') {
      try { metadata = JSON.parse(metadata) } catch { metadata = {} }
    }
    const data = metadata.display_data || {}
    if (item.item_type === 'progress_display') {
      for (const tile of progressPreviewTiles(data)) {
        add(tile.mediaId, `preview:${tile.key}`, `${data.title || 'Batch'} · Option ${tile.option}`)
      }
    }
    if (item.item_type === 'media_display') {
      for (const [index, row] of (data.rows || []).entries()) {
        add(row.input?.input_image?.media_id, `row:${index}:input`)
        for (const [refIndex, reference] of (row.input?.ref_images || []).entries()) add(reference.media_id, `row:${index}:ref:${refIndex}`)
        if (!row.output?.deleted && row.output?.status !== 'trashed') add(row.output?.media_id, `row:${index}:output`)
      }
    }
    if (item.item_type === 'scored_results') {
      for (const [index, result] of (metadata.scored_data?.items || []).entries()) add(result.media_id, `scored:${index}`)
    }
    if (item.item_type === 'analysis_result') add(metadata.analysis_data?.media_id, 'analysis')
    if (item.item_type === 'grid_generation') add(data.grid_media_id, 'grid')
    if (item.item_type === 'assistant_message') {
      let index = 0
      const text = (item.message_text || '').replace(/<think(?:ing)?>([\s\S]*?)(<\/think(?:ing)?>|$)/gi, '').trim()
      // Match rendered Markdown images, excluding examples in code blocks.
      marked.walkTokens(marked.lexer(text), token => {
        if (token.type !== 'image') return
        const match = token.href.match(/^media(?:_id=|:)(\d+)$/)
        if (match) add(Number(match[1]), `message:${index++}`)
      })
    }
  }
  return entries
}
