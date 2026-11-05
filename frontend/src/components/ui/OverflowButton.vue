<script setup lang="ts">
// The one overflow button (DESIGN.md §1.10): horizontal dots, bare, on every
// header, row and panel. Menus open from it; the button only draws the glyph.
import { EllipsisHorizontalIcon } from '@heroicons/vue/24/outline'
import IconButton from './IconButton.vue'

defineOptions({ inheritAttrs: false })
withDefaults(defineProps<{ label?: string }>(), { label: 'More options' })
</script>

<template>
  <IconButton v-bind="$attrs" :title="label" :aria-label="label">
    <EllipsisHorizontalIcon class="h-icon-nav w-icon-nav" />
  </IconButton>
</template>
