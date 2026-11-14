import { ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { placeFromLocale } from '../utils/peopleFrom'

type Place = { code: string; name: string }

// One app-wide setting, shared by every Fluent control on the page.
const value = ref<string | null>(null)
const places = ref<Place[]>([])
let loading: Promise<void> | null = null

async function put(next: string): Promise<void> {
  const { data } = await axios.put(`${getApiBase()}/prompt-programs/people-from`, { value: next })
  value.value = data.value ?? next
}

/** Where people are from by default. The first time it loads unset, it is set from the
    browser's region (no region: anywhere). */
export function usePeopleFrom() {
  if (!loading) {
    loading = (async () => {
      try {
        const { data } = await axios.get(`${getApiBase()}/prompt-programs/people-from`)
        places.value = Array.isArray(data.places) ? data.places : []
        value.value = data.value ?? null
        if (!value.value) await put(placeFromLocale(navigator.language, places.value.map(p => p.code)))
      } catch {
        loading = null   // try again next time a control loads
      }
    })()
  }
  return {
    value,
    places,
    set: async (next: string) => {
      const was = value.value
      value.value = next
      try { await put(next) } catch { value.value = was }
    },
  }
}
