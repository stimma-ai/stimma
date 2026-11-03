import { createApp, h, ref } from 'vue'
import { useLoraPool } from '../../src/composables/useLoraPool'
import LoraPoolPanel from '../../src/components/generation/LoraPoolPanel.vue'

const TOOL = 'fake:tool'
const NOTED = 'series/clay_000000500.safetensors'
const SIBLING = 'series/clay_000001000.safetensors'
const PLAIN = 'old/plain.ckpt'

const items = ref<any>({
  [NOTED]: {
    fingerprint: 'stfp1:a',
    note: { trigger_words: ['clayrndr'], notes: 'Clay look.', shared: false, linked_count: 1 },
    series: { id: 'series/clay', size: 2, default_shared: false },
  },
  [SIBLING]: { fingerprint: 'stfp1:b', note: null, series: { id: 'series/clay', size: 2, default_shared: false } },
  [PLAIN]: { fingerprint: null, note: null, series: null },
})
const calls: any[] = ((window as any).calls = [])
const notesApi = {
  items,
  refresh: async () => {},
  save: async (value: string, trigger_words: string[], notes: string) => {
    calls.push({ save: value, trigger_words, notes })
  },
  share: async (value: string, replace = false) => {
    calls.push({ share: value, replace })
    return replace ? 0 : 1
  },
  unshare: async () => {},
}

const verbatim = ref<string | null>(null)
;(window as any).setVerbatim = (value: string | null) => { verbatim.value = value }
const inserted: string[] = ((window as any).inserted = [])

const pool = useLoraPool()
pool.addToPool(TOOL, { path: NOTED, name: NOTED })
pool.addToPool(TOOL, { path: SIBLING, name: SIBLING })
pool.addToPool(TOOL, { path: PLAIN, name: PLAIN })

createApp({
  render: () => h(LoraPoolPanel, {
    toolId: TOOL,
    modelName: null,
    availableLoras: [NOTED, SIBLING, PLAIN].map(path => ({ path, name: path })),
    loraNotes: notesApi as any,
    verbatimPrompt: verbatim.value,
    onInsertTrigger: (word: string) => inserted.push(word),
  }),
}).mount('#app')

