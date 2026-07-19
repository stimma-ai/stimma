export function shouldShowTagInPicker(tag, pendingAction = null) {
  return Number(tag?.usage_count || 0) > 0 || pendingAction === 'add'
}
