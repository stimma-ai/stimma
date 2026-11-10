import { computed, createApp, h, ref } from 'vue'
import '../../src/style.css'
import FluentControl from '../../src/components/generation/FluentControl.vue'
import { addToast, clearToasts, useToasts } from '../../src/composables/useToasts'
import { switchDeclinedToDirect, wasDeclined } from '../../src/utils/fluentSubmit'

// Tool View's prompt box, cut down to what a declined prompt touches: the prompt menu (the
// real FluentControl), the saved prompt options, and the toasts. `run()` is a submit's
// after-run step, the one Tool View calls.
const promptOptions = ref<any>({ autoImprove: { enabled: true, level: 'expand' } })
const direct = computed(() => !!promptOptions.value.direct)
const raw = computed(() => !!promptOptions.value.raw)
// What usePromptProgram holds once the server answered "declined" for this prompt. Like
// the real one, it's 'off' whenever the box isn't in Fluent.
const declinedHere = ref(true)
const program = {
  status: computed(() => (direct.value || raw.value ? 'off' : declinedHere.value ? 'error' : 'stale')),
  error: computed(() => (declinedHere.value ? { sig: 's', code: 'prepare_declined', message: 'The chat model declined this prompt, so it is used as written.' } : null)),
  unsupported: computed(() => false),
  choices: computed(() => []),
  prepare: async () => { (window as any).prepared = ((window as any).prepared || 0) + 1; return false },
  rethink: async () => false,
  ensureReady: async () => false,
}
const runs: string[] = ((window as any).runs = [])

;(window as any).run = () => {
  const declined = wasDeclined({ status: program.status.value as any, code: program.error.value?.code })
  runs.push(direct.value ? 'direct' : 'fluent')
  switchDeclinedToDirect({
    declined, direct: direct.value, promptOptions: promptOptions.value,
    set: (next) => { promptOptions.value = next },
    notify: (message) => addToast(message, 'info', 60_000),
  })
}
;(window as any).state = () => promptOptions.value
;(window as any).clearToasts = clearToasts

const { toasts } = useToasts()
createApp({
  render: () => h('div', { class: 'p-6' }, [
    h(FluentControl, {
      program: program as any, raw: raw.value, direct: direct.value, enhance: 'expand', llmUnconfigured: false,
      modelName: 'Test model',
      // Tool View's own handler for the menu's tabs.
      onWay: (w: string) => { promptOptions.value = { ...promptOptions.value, raw: w === 'raw' || undefined, direct: w === 'direct' || undefined } },
    }),
    h('div', { 'data-toasts': '' }, toasts.value.map(t => h('p', { 'data-toast': t.type }, t.message))),
  ]),
}).mount('#app')
