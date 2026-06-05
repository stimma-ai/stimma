import { ref } from 'vue'

// One-shot hand-off for "attach this media when the destination view loads".
// Deliberately NOT a URL query param: a query param lives in browser history, so
// back/forward navigation re-fires the attachment (the "resuscitation" bug), and
// the async router.replace used to strip it races with the push that set it,
// which also breaks the back button. This store is consumed exactly once and
// never enters history.
//
// Shape: { target: 'chat' | 'home', chatId: number | null, mediaIds: number[] }
export const pendingMedia = ref(null)

export function setPendingMedia(target, mediaIds, chatId = null) {
  const ids = (mediaIds || []).map(Number).filter(Number.isInteger)
  if (ids.length === 0) return
  pendingMedia.value = {
    target,
    chatId: chatId == null ? null : Number(chatId),
    mediaIds: ids
  }
}

// Returns the pending media IDs (and clears the store) if they were destined for
// this target/chat; otherwise returns null and leaves the store untouched.
export function consumePendingMedia(target, chatId = null) {
  const p = pendingMedia.value
  if (!p || p.target !== target) return null
  if (target === 'chat' && chatId != null && p.chatId !== chatId) return null
  pendingMedia.value = null
  return p.mediaIds
}
