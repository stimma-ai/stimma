// Which hitl_response answers a hitl_request card. A response names the
// request it answers (request_item_id); one saved before responses carried
// that id answers every request before it.

function metadata(item: any): any {
  const meta = item?.item_metadata
  if (!meta) return null
  if (typeof meta !== 'string') return meta
  try {
    return JSON.parse(meta)
  } catch {
    return null
  }
}

export function answeredRequestId(responseItem: any): number | null {
  const meta = metadata(responseItem)
  return meta?.request_item_id ?? meta?._mcp_interaction_id ?? null
}

export function findHitlResponseItem(items: any[], requestItem: any): any | null {
  const index = items.findIndex(item => item.id === requestItem.id)
  if (index < 0) return null
  for (let i = index + 1; i < items.length; i++) {
    const item = items[i]
    if (item.item_type !== 'hitl_response') continue
    const answered = answeredRequestId(item)
    if (answered == null || answered === requestItem.id) return item
  }
  return null
}

// The answer as the cards read it: permission responses are flat
// ({ approved, scope }); plan approvals nest it ({ response: { ... } }).
export function hitlResponseData(responseItem: any): any | null {
  if (!responseItem) return null
  const meta = metadata(responseItem)
  return meta?.response || meta || null
}
