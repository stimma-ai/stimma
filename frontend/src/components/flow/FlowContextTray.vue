<template>
  <!-- With no references the tray is only a hint, shown while the message
       field is empty (the shell's textarea shows its placeholder) so a
       message being written doesn't carry a permanent extra line. Once
       references are attached it becomes a flex-wrapped chip strip. -->
  <div
    :class="refs.items.value.length === 0 ? 'px-4' : 'flex flex-wrap items-center gap-1.5 border-b border-edge-subtle px-4 py-2'"
  >
    <span
      v-if="refs.items.value.length === 0"
      class="-mb-1 hidden pt-2.5 text-[11px] text-content-muted [[data-composer-shell]:has(textarea:placeholder-shown)_&]:block"
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
