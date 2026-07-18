<template>
  <div class="bg-surface border-b border-edge-subtle px-6 py-2.5">
    <div class="flex items-center justify-between">
      <div class="min-w-0">
        <div class="inline-flex max-w-full items-center gap-2">
          <ArchiveBoxIcon
            class="h-4 w-4 flex-shrink-0"
            :class="isEditingName || project.name ? 'text-content-secondary' : 'text-content-muted'"
          />
          <input
            v-if="isEditingName"
            ref="nameInputRef"
            v-model="draftName"
            type="text"
            placeholder="Name this project..."
            autofocus
            class="w-full max-w-[360px] min-w-0 border-0 bg-transparent px-0 py-0 text-[15px] font-medium text-content placeholder:text-content-muted focus:outline-none"
            @blur="saveName"
            @keydown.enter.prevent="saveName"
            @keydown.esc.prevent="cancelEdit"
          />
          <button
            v-else
            class="truncate text-left text-[15px] font-medium transition-colors hover:text-content"
            :class="project.name ? 'text-content' : 'italic text-content-muted'"
            @click="handleProjectChipClick"
          >
            {{ project.name || 'Name this project...' }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-1 overflow-x-auto">
        <button
          v-for="item in navItems"
          :key="item.name"
          class="px-2.5 py-1 text-[13px] rounded-md whitespace-nowrap transition-colors"
          :class="activeName === item.name
            ? 'text-accent font-medium bg-accent/15'
            : 'text-content-tertiary hover:text-content-secondary hover:bg-overlay-faint'"
          @click="router.push({ name: item.name, params: { id: project.id } })"
        >
          <svg v-if="item.icon" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
          <template v-else>{{ item.label }}</template>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { ArchiveBoxIcon } from '@heroicons/vue/24/outline'
import { useRoute, useRouter } from 'vue-router'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  project: {
    type: Object,
    required: true
  },
  activeName: {
    type: String,
    default: ''
  }
})

const router = useRouter()
const route = useRoute()
const { updateProject } = useMediaApi()
const isEditingName = ref(false)
const draftName = ref('')
const nameInputRef = ref(null)
const navItems = [
  { name: 'project-overview', label: 'Overview' },
  { name: 'project-tools', label: 'Tools' },
  { name: 'project-assets', label: 'Assets' },
  { name: 'project-boards', label: 'Boards' },
  { name: 'project-chats', label: 'Chats' },
  { name: 'project-flows', label: 'Flows' },
  { name: 'project-settings', icon: true }
]

async function startEdit() {
  draftName.value = props.project.name || ''
  isEditingName.value = true
  await nextTick()
  nameInputRef.value?.focus()
  nameInputRef.value?.select()
}

function cancelEdit() {
  isEditingName.value = false
  draftName.value = props.project.name || ''
}

async function saveName() {
  const nextName = draftName.value.trim()
  isEditingName.value = false
  if (nextName === (props.project.name || '')) return
  const updated = await updateProject(props.project.id, { name: nextName })
  Object.assign(props.project, updated)
}

async function handleProjectChipClick() {
  if (String(route.name || '') !== 'project-overview') {
    await router.push({ name: 'project-overview', params: { id: props.project.id } })
    return
  }
  await startEdit()
}


watch(
  () => [route.query.rename, route.params.id, props.project.id],
  async () => {
    if (route.query.rename !== '1') return
    if (String(route.params.id) !== String(props.project.id)) return
    await startEdit()
    const nextQuery = { ...route.query }
    delete nextQuery.rename
    router.replace({ name: route.name, params: route.params, query: nextQuery })
  },
  { immediate: true }
)

</script>
