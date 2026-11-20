<template>
  <!-- A chat bubble with a plus: add this picture to the message. Checked once it's in. -->
  <svg fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor" aria-hidden="true">
    <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
    <path v-if="checked" stroke-linecap="round" stroke-linejoin="round" d="M8.75 9.9l2.1 2.1 4.4-4.4" />
    <path v-else stroke-linecap="round" stroke-linejoin="round" d="M12 6.9v5.8M9.1 9.8h5.8" />
  </svg>
</template>

<script setup>
defineProps({ checked: { type: Boolean, default: false } })
</script>
