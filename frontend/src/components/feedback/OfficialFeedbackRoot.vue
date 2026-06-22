<template>
  <FeedbackModal />

  <FeedbackConsentDialog
    :show="feedbackConsentDialog.open"
    subject="thumbs"
    @dont-send="consentDontSend"
    @send-once="consentSendOnce"
    @always-send="consentAlwaysSend"
  />

  <FeedbackConsentDialog
    :show="crashDialog.open"
    subject="crash"
    :crash-count="crashDialog.reports.length"
    @dont-send="crashDecision('dismiss')"
    @send-once="crashDecision('send')"
    @always-send="crashDecision('send_always')"
  />
</template>

<script setup>
import { onMounted } from 'vue'
import FeedbackModal from './FeedbackModal.vue'
import FeedbackConsentDialog from './FeedbackConsentDialog.vue'
import { useFeedback } from '../../composables/useFeedback'
import { useWebSocket } from '../../composables/useWebSocket'

const {
  consentDialog: feedbackConsentDialog,
  crashDialog,
  consentDontSend,
  consentSendOnce,
  consentAlwaysSend,
  crashDecision,
  loadState: loadFeedbackState,
  checkPendingCrashes,
  initCrashNotifications,
} = useFeedback()

onMounted(() => {
  loadFeedbackState().then(() => {
    checkPendingCrashes()
  })
  initCrashNotifications(useWebSocket().on)
})
</script>
