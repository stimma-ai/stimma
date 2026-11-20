import { createApp, h, reactive } from 'vue'
import ChatModelPicker from '../../src/components/chat/ChatModelPicker.vue'
import RoleModelRows from '../../src/components/settings/RoleModelRows.vue'
import '../../src/style.css'
import { setLoadRetryDelays } from '../../src/utils/loadRetry.js'

// A failed catalog read retries quickly here; no other test fails one.
setLoadRetryDelays([300])

const state = reactive({ modelSlug: null as string | null, roles: {} as Record<string, string> })
;(window as any).pickerTest = state
createApp({ render: () => h(ChatModelPicker, {
  modelSlug: state.modelSlug,
  'onUpdate:modelSlug': (slug: string) => { state.modelSlug = slug },
}) }).mount('#app')
createApp({ render: () => h(RoleModelRows, { modelValue: state.roles }) }).mount('#settings')
