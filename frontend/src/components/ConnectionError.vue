<template>
  <EmptyState
    icon="warning"
    tone="error"
    :title="errorTitle"
    :subtitle="errorSubtitle"
    :action-label="showRetry ? 'Retry' : null"
    @action="$emit('retry')"
  />
</template>

<script setup>
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'

const props = defineProps({
  message: {
    type: String,
    default: ''
  },
  showRetry: {
    type: Boolean,
    default: true
  },
  statusCode: {
    type: Number,
    default: null
  }
})

defineEmits(['retry'])

const errorTitle = computed(() => {
  if (props.statusCode) {
    if (props.statusCode === 404) {
      return 'Not found'
    }
    if (props.statusCode >= 400 && props.statusCode < 500) {
      return 'Request error'
    }
    if (props.statusCode >= 500) {
      return 'Server error'
    }
  }
  return 'Stimma is unavailable'
})

const errorSubtitle = computed(() => {
  if (props.message) {
    return props.message
  }
  if (props.statusCode) {
    if (props.statusCode === 404) {
      return 'The requested resource could not be found'
    }
    if (props.statusCode >= 400 && props.statusCode < 500) {
      return 'There was a problem with the request'
    }
    if (props.statusCode >= 500) {
      return 'Something went wrong on the server'
    }
  }
  return 'Check your connection and try again'
})
</script>
