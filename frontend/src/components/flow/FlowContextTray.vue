<template>
  <!-- Empty state: a dashed-border hint strip so the user can see where to
       drop references. When populated, becomes a flex-wrapped chip strip. -->
  <div
    class="flex flex-wrap items-center gap-1.5 px-2.5 py-1.5 border-b border-edge-subtle bg-surface/60"
    :class="refs.items.value.length === 0 ? 'border-dashed' : ''"
  >
    <span
      v-if="refs.items.value.length === 0"
      class="text-[11px] text-content-muted italic"
    >
      Reference items from the flow to give the agent context
    </span>
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
