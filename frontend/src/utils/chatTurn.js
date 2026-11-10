import { collectChatMedia } from './chatMedia.js'

// The current turn: everything after the last message the person sent.
function turnItems(items) {
  let start = 0
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i]?.item_type === 'user_message') { start = i + 1; break }
  }
  return items.slice(start)
}

// Media the current turn made: outputs only, never the inputs and references
// a display row shows beside them. Each media id once, in order.
export function turnOutputMediaIds(items) {
  const seen = new Set()
  const out = []
  for (const entry of collectChatMedia(turnItems(items))) {
    if (/:(input|ref:\d+)$/.test(entry.slot)) continue
    if (seen.has(entry.id)) continue
    seen.add(entry.id)
    out.push(entry.id)
  }
  return out
}

// The turn ended with something the agent said (rather than only work):
// its last item is an assistant message with visible text.
export function turnEndedWithReply(items) {
  const turn = turnItems(items)
  for (let i = turn.length - 1; i >= 0; i--) {
    const item = turn[i]
    if (item?.item_type !== 'assistant_message') continue
    const text = (item.message_text || '').replace(/<think(?:ing)?>([\s\S]*?)(<\/think(?:ing)?>|$)/gi, '').trim()
    return text.length > 0
  }
  return false
}

// What the person sent most recently (to show on a dock row before results).
export function lastSentMediaIds(items) {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]
    if (item?.item_type !== 'user_message') continue
    let metadata = item.item_metadata || {}
    if (typeof metadata === 'string') {
      try { metadata = JSON.parse(metadata) } catch { metadata = {} }
    }
    return (metadata.attachments || []).map(a => a?.media_id).filter(id => typeof id === 'number')
  }
  return []
}
