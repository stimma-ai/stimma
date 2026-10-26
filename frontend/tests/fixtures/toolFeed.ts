import { createApp, h, onMounted } from 'vue'
import { initApiConfig } from '../../src/apiConfig'
import { useWebSocket } from '../../src/composables/useWebSocket'
import { useGenerationJobs } from '../../src/composables/useGenerationJobs'

// A tool view's job feed, as ToolView drives it: init() is awaited before
// the tool renders, then the feed paints its jobs.
const app = createApp({
  setup() {
    const feed = useGenerationJobs({ taskType: null, generatorInstanceId: 'tool-test:feed@@guid' })
    onMounted(async () => {
      await feed.init()
      window.feedInitialized = true
    })
    return () => h('ul', feed.jobs.value.map(job => h('li', { class: 'job', 'data-id': job.id }, String(job.id))))
  },
})
initApiConfig().then(() => {
  useWebSocket().connect()
  app.mount('#app')
})
