import { createApp, h } from 'vue'
import BackgroundWorkPanel from '../../src/components/BackgroundWorkPanel.vue'
import BackgroundWorkIndicator from '../../src/components/BackgroundWorkIndicator.vue'
import { useBackgroundWork } from '../../src/composables/useBackgroundWork'

createApp({
  setup() {
    const work = useBackgroundWork()
    work.statsLoading.value = false
    window.backgroundWork = work
    return () => [
      work.hasActiveWork.value ? h('div', { 'data-testid': 'indicator' }, [h(BackgroundWorkIndicator)]) : null,
      h(BackgroundWorkPanel),
    ]
  },
}).mount('#app')
