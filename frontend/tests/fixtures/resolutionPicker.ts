import { createApp, h, reactive } from 'vue'
import ResolutionPicker from '../../src/components/ResolutionPicker.vue'
import '../../src/style.css'

const axis = { minimum: 256, maximum: 4096, 'x-step': 64 }
const state = reactive({
  policy: { ratio: '1:1', mp: 4, tier: 1024, followShape: false, followSize: false },
  schema: { width: { ...axis, 'x-resolution-slider-max-pixels': 4194304 }, height: { ...axis } } as Record<string, any>,
})
;(window as any).resolutionTest = state
createApp({ render: () => h(ResolutionPicker, {
  policy: state.policy, schemaProps: state.schema,
  'onUpdate:policy': (policy: typeof state.policy) => { state.policy = policy },
}) }).directive('no-autocorrect', {}).mount('#app')
