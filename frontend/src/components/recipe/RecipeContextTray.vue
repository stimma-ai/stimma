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
      Reference items from the recipe to give the agent context
    </span>
    <RecipeRefChip
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
import { useRecipeReferences, injectRecipeChatIdRef } from '../../composables/useRecipeReferences'
import RecipeRefChip from './RecipeRefChip.vue'

const refs = useRecipeReferences(injectRecipeChatIdRef())
</script>
