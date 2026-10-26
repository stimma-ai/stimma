import { createApp, h } from 'vue'
import BackgroundWorkPanel from '../../src/components/BackgroundWorkPanel.vue'
import BackgroundWorkIndicator from '../../src/components/BackgroundWorkIndicator.vue'
import { applyStatsEvent, useBackgroundWork } from '../../src/composables/useBackgroundWork'
window.applyStatsEvent = applyStatsEvent

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
