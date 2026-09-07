import { createApp, h } from 'vue'
import AppImage from '../../src/components/media/AppImage.vue'
import { mobileForeground, mobileAutoplayAllowed, allowMobilePlayback } from '../../src/composables/useMobilePlaybackLifecycle.js'
import { createMobileKeepAwakeLease } from '../../src/desktop/mobileBridge.ts'

Object.assign(window, {
  readiness: {
    mobileForeground, mobileAutoplayAllowed, allowMobilePlayback, createMobileKeepAwakeLease,
    mountImages() {
      createApp({ render: () => h('div', [
        h('div', { id: 'steady' }, [h(AppImage, { src: 'https://media.test/steady.png', loading: 'eager', containerClass: 'test-tile' })]),
        h('div', { id: 'failed' }, [h(AppImage, { src: 'https://media.test/failed.png', loading: 'eager', queued: true, containerClass: 'test-tile' })]),
        h('div', { id: 'offscreen', style: { marginTop: '1500px' } }, [h(AppImage, { src: 'https://media.test/offscreen.png', loading: 'eager', containerClass: 'test-tile' })]),
      ]) }).mount('#app')
    },
  },
})
