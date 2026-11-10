import { ref, watch } from 'vue'

export interface OpenCard { id: string; anchor: DOMRect }

/** Which choice card is open and where it hangs from. A card only opens on a choice
    that's shown, and closes itself when its choice goes (a prepare that lands while
    it's open may not have it), so it never shows empty. */
export function createChoiceCard(byId: { readonly value: Record<string, unknown> }) {
  const openCard = ref<OpenCard | null>(null)
  function open(id: string | null | undefined, el: Element | null) {
    if (!id || !el || !byId.value[id]) return
    openCard.value = { id, anchor: el.getBoundingClientRect() }
  }
  function close() { openCard.value = null }
  watch(() => !!openCard.value && !byId.value[openCard.value.id], (gone) => { if (gone) close() }, { flush: 'sync' })
  return { openCard, open, close }
}
