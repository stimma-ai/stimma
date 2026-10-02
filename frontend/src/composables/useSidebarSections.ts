import { ref } from 'vue'
import { makeProfileKey } from '../utils/storageKeys'

// Collapsed sidebar sections are a layout preference stored like the sidebar
// width (per profile, shared across windows). The key is resolved on first
// use, after the profile is known, not at import time.
const storageKey = () => makeProfileKey('sidebar', 'collapsed_sections')

const collapsed = ref<Set<string> | null>(null)

function sections(): Set<string> {
  if (collapsed.value) return collapsed.value
  let loaded = new Set<string>()
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey()) || '[]')
    if (Array.isArray(parsed)) loaded = new Set(parsed.filter(v => typeof v === 'string'))
  } catch { /* corrupt or unavailable storage: start expanded */ }
  collapsed.value = loaded
  return loaded
}

export function useSidebarSections() {
  function isCollapsed(id: string) {
    return sections().has(id)
  }
  function toggleSection(id: string) {
    const next = new Set(sections())
    if (next.has(id)) next.delete(id)
    else next.add(id)
    collapsed.value = next
    try { localStorage.setItem(storageKey(), JSON.stringify([...next])) } catch { /* layout still toggles */ }
  }
  return { isCollapsed, toggleSection }
}
