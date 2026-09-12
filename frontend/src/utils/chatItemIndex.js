// Build once per history change. A result belongs to the preceding call with
// the same transport ID; retries can reuse that ID, so a plain result-by-ID
// map would incorrectly attach an old result to a new call.
export function buildChatItemIndex(items) {
  const byId = new Map()
  const children = new Map()
  const toolResults = new Map()
  const firstToolCalls = new Map()
  const childResults = new Map()
  const pendingCalls = new Map()
  for (const item of items) {
    byId.set(item.id, item)
    if (item.parent_item_id != null) {
      let siblings = children.get(item.parent_item_id)
      if (!siblings) children.set(item.parent_item_id, siblings = [])
      siblings.push(item)
    }
    if (item.item_type === 'tool_call') {
      pendingCalls.set(item.tool_call_id, item)
      if (!firstToolCalls.has(item.tool_call_id)) firstToolCalls.set(item.tool_call_id, item)
    } else if (item.item_type === 'tool_result') {
      const call = pendingCalls.get(item.tool_call_id)
      if (call) {
        toolResults.set(call.id, item)
        pendingCalls.delete(item.tool_call_id)
      }
      // Nested timelines historically use the first matching sibling result.
      let results = childResults.get(item.parent_item_id)
      if (!results) childResults.set(item.parent_item_id, results = new Map())
      if (!results.has(item.tool_call_id)) results.set(item.tool_call_id, item)
    }
  }
  return { byId, children, toolResults, firstToolCalls, childResults }
}
