import { ref, watch, onUnmounted, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface LoraNote {
  trigger_words: string[]
  notes: string
  shared: boolean
  linked_count: number
}

export interface LoraNoteItem {
  fingerprint: string | null
  note: LoraNote | null
  series: { id: string; size: number; default_shared: boolean } | null
}

const PENDING_POLL_MS = 5000

/**
 * Trigger words and notes for one tool's LoRAs. A note belongs to the file's
 * content fingerprint, so a LoRA without a fingerprint can't have one.
 */
export function useLoraNotes(toolId: Ref<string | null>, enabled: Ref<boolean>) {
  const items = ref<Record<string, LoraNoteItem>>({})
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let requestId = 0

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
  }

  async function refresh() {
    stopPolling()
    const id = toolId.value
    if (!id || !enabled.value) {
      items.value = {}
      return
    }
    const current = ++requestId
    try {
      const { data } = await axios.get(`${getApiBase()}/lora-notes`, { params: { tool_id: id } })
      if (current !== requestId) return
      items.value = data.items || {}
      if (data.pending > 0) pollTimer = setTimeout(refresh, PENDING_POLL_MS)
    } catch {
      if (current === requestId) items.value = {}
    }
  }

  async function save(value: string, triggerWords: string[], notes: string) {
    const fingerprint = items.value[value]?.fingerprint
    if (!fingerprint) return
    await axios.put(`${getApiBase()}/lora-notes/files/${encodeURIComponent(fingerprint)}`, {
      trigger_words: triggerWords,
      notes,
      value,
    })
    await refresh()
  }

  /** Share with the series. Returns how many other files' notes it would replace, if any. */
  async function share(value: string, replace = false): Promise<number> {
    const fingerprint = items.value[value]?.fingerprint
    if (!fingerprint || !toolId.value) return 0
    try {
      await axios.post(`${getApiBase()}/lora-notes/files/${encodeURIComponent(fingerprint)}/share`, {
        tool_id: toolId.value,
        value,
        replace,
      })
    } catch (err: any) {
      if (err?.response?.status === 409) return err.response.data?.detail?.conflicts ?? 1
      throw err
    }
    await refresh()
    return 0
  }

  async function unshare(value: string) {
    const fingerprint = items.value[value]?.fingerprint
    if (!fingerprint) return
    await axios.post(`${getApiBase()}/lora-notes/files/${encodeURIComponent(fingerprint)}/unshare`)
    await refresh()
  }

  watch([toolId, enabled], refresh, { immediate: true })
  onUnmounted(stopPolling)

  return { items, refresh, save, share, unshare }
}

export type LoraNotes = ReturnType<typeof useLoraNotes>
