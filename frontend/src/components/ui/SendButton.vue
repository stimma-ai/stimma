<script setup lang="ts">
// The composer's send (and stop) button (DESIGN.md §3.5b). One 32px control
// shape (rounded-md, §1.3) inside a target that grows to 44px on coarse
// pointers. Enabled = the crisp accent fill with its on-accent glyph.
// Disabled = a faint fill with a muted glyph at half strength, quieter than
// any other shape in the composer. Behaviour, title and aria attributes come
// from the caller.
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  /** send = arrow; stop = square (a run in progress). */
  icon?: 'send' | 'stop'
  disabled?: boolean
}>(), { icon: 'send', disabled: false })
</script>

<template>
  <button
    type="button"
    v-bind="$attrs"
    :disabled="disabled"
    class="group flex h-8 w-8 flex-none items-center justify-center focus-visible:outline-none coarse:h-11 coarse:w-11 disabled:cursor-not-allowed"
  >
    <span
      class="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-on transition-colors duration-150 group-hover:bg-accent/90 group-focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface group-disabled:bg-overlay-subtle group-disabled:text-content-muted group-disabled:opacity-50 group-disabled:group-hover:bg-overlay-subtle"
    >
      <svg v-if="icon === 'stop'" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="h-icon-inline w-icon-inline" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="1" />
      </svg>
      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="h-icon-nav w-icon-nav" aria-hidden="true">
        <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)" />
      </svg>
    </span>
  </button>
</template>
