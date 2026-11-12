import { computed, createApp, h, ref } from 'vue'
import '../../src/style.css'
import FluentControl from '../../src/components/generation/FluentControl.vue'
import type { EnhanceLevel } from '../../src/composables/usePromptProgram'

// Tool View's prompt menu on its own, with a stand-in for the prepared prompt. The detail
// level is the menu's own setting, so `window.level()` reads what it was set to.
const level = ref<EnhanceLevel>('fill')
const hasLoras = ref(true)
const program: any = {
  status: computed(() => 'ready'),
  unsupported: computed(() => false),
  error: ref(null),
  program: ref({ key: 'k1', slots: [], choices: [] }),
  slots: computed(() => []),
  choices: computed(() => []),
  prepare: async () => true,
  ensureReady: async () => true,
  fetchProgramText: async () => ({ program: 'emit("a dorm room")', reading: null }),
  previewRuns: async () => [],
}
;(window as any).level = () => level.value

createApp({
  render: () => h('div', { class: 'p-4' }, [
    h(FluentControl, {
      program,
      raw: false,
      direct: false,
      enhance: level.value,
      llmUnconfigured: false,
      modelName: 'Krea 2',
      hasLoras: hasLoras.value,
      loraTriggers: true,
      loraNotes: true,
      lastPrompt: 'a dorm room with a 24-year-old Korean man, warm lamp light',
      onMode: (v: EnhanceLevel) => { level.value = v },
    }),
  ]),
}).mount('#app')
