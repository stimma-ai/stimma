<template>
  <div class="flex-1 flex flex-col items-center justify-center gap-4 text-center px-4">
    <!-- Icon container. 'error' tone tints the circle so error states stop
         rendering identical to plain empty states (STANDARDS.md §3, "Empty
         state" recipe). -->
    <div :class="['w-12 h-12 rounded-full flex items-center justify-center', tone === 'error' ? 'bg-red-500/10' : 'bg-overlay-subtle']">
      <!-- Slot for custom icon, or use built-in icons based on 'icon' prop -->
      <slot name="icon">
        <!-- exclamation-triangle (warning/error) -->
        <svg v-if="icon === 'warning'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <!-- trash -->
        <svg v-else-if="icon === 'trash'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
        </svg>
        <!-- photo (media/images) -->
        <svg v-else-if="icon === 'photo'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.008v.008h-.008V8.25Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
        </svg>
        <!-- folder/board -->
        <svg v-else-if="icon === 'folder'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z" />
        </svg>
        <!-- magnifying-glass (search/filter) -->
        <svg v-else-if="icon === 'search'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
        </svg>
        <!-- funnel (filters) -->
        <svg v-else-if="icon === 'funnel'" :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 0 1-.659 1.591l-5.432 5.432a2.25 2.25 0 0 0-.659 1.591v2.927a2.25 2.25 0 0 1-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 0 0-.659-1.591L3.659 7.409A2.25 2.25 0 0 1 3 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0 1 12 3Z" />
        </svg>
        <!-- Default: question-mark-circle -->
        <svg v-else :class="['w-6 h-6', tone === 'error' ? 'text-red-400' : 'text-content-muted']" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12v-.008Z" />
        </svg>
      </slot>
    </div>

    <!-- Title and subtitle -->
    <div class="flex flex-col gap-1">
      <div class="text-content-tertiary text-lg font-medium">{{ title }}</div>
      <div v-if="subtitle" class="text-content-muted text-sm">{{ subtitle }}</div>
    </div>

    <!-- Optional action button -->
    <button
      v-if="actionLabel"
      @click="$emit('action')"
      class="mt-2 px-5 py-2 text-sm bg-overlay-light hover:bg-overlay-medium rounded-lg text-content-secondary hover:text-content transition-colors"
    >
      {{ actionLabel }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  icon: {
    type: String,
    default: null,
    validator: (value) => ['warning', 'trash', 'photo', 'folder', 'search', 'funnel', null].includes(value)
  },
  title: {
    type: String,
    required: true
  },
  subtitle: {
    type: String,
    default: null
  },
  actionLabel: {
    type: String,
    default: null
  },
  /** 'error' tints the icon circle red so error states read distinctly
      from plain empty states (ConnectionError.vue). */
  tone: {
    type: String,
    default: 'neutral',
    validator: (value) => ['neutral', 'error'].includes(value)
  }
})

defineEmits(['action'])
</script>
