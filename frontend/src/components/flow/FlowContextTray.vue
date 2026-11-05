<template>
  <!-- Attached references are a flex-wrapped chip strip. With none the tray
       renders nothing: the composer's placeholder carries the hint, so the
       field never changes height when typing starts. -->
  <div
    v-if="refs.items.value.length > 0"
    class="flex flex-wrap items-center gap-1.5 border-b border-edge-subtle px-4 py-2"
  >
    <FlowRefChip
      v-for="r in refs.items.value"
      :key="r.refKey"
      :label="r.label"
      :breadcrumb="r.breadcrumb"
      variant="composer"
      :closable="true"
      @hover="(on) => refs.setHovered(on ? r.refKey : null)"
      @close="refs.remove(r.refKey)"
    />
  </div>
</template>

<script setup lang="ts">
import { useFlowReferences, injectFlowChatIdRef } from '../../composables/useFlowReferences'
import FlowRefChip from './FlowRefChip.vue'

const refs = useFlowReferences(injectFlowChatIdRef())
</script>
