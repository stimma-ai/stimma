<template>
  <div class="h-full flex flex-col bg-base">
    <div class="flex-1 overflow-y-auto">
      <div class="max-w-4xl mx-auto px-6 py-6 h-full">
        <StimpacksSection />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import StimpacksSection from '../components/settings/sections/StimpacksSection.vue'
</script>
