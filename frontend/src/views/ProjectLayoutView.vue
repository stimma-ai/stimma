<template>
  <!-- Keep each project sub-screen (Assets/Boards/Overview/...) alive. The outer
       KeepAlive (App.vue, keyed per project) caches this layout, but the inner
       <router-view> stays reactive even while the layout is cached — so when the
       global route navigates away (e.g. to a tool) it would otherwise see "no
       nested match" and destroy the active sub-view, losing its scroll/state.
       Keep-aliving here preserves the sub-view instance so returning reactivates
       it (onActivated) instead of remounting — same behavior as the main browser. -->
  <router-view v-if="project" v-slot="{ Component }">
    <KeepAlive>
      <component :is="Component" :project="project" />
    </KeepAlive>
  </router-view>
</template>

<script setup>
import { onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaApi } from '../composables/useMediaApi'
import { useProjectRoute } from '../composables/useProjectRoute'
import { useWorkingContext } from '../composables/useWorkingContext'
import { addToast } from '../composables/useToasts'
import { contextSection } from '../utils/workingContext'
import { setCompactTitle } from '../composables/useCompactChrome'

const route = useRoute()
const router = useRouter()
const ownId = Number(route.params.id)
const { activeProject, rememberProject, selectProject } = useWorkingContext()
const { getProject } = useMediaApi()
const { setLastProjectRoute } = useProjectRoute()

const project = ref(null)

provide('projectRef', project)

async function loadProject() {
  try {
    const loaded = await getProject(ownId)
    project.value = loaded
    rememberProject(loaded)
  } catch {
    if (String(route.name || '').startsWith('project-') && Number(route.params.id) === ownId) {
      addToast('This project is no longer available.', 'warning')
      selectProject(null)
      await router.replace({ name: 'browse', query: { library: '1' } })
    }
  }
}

// Remember the active project sub-screen per project id so re-entering the
// project from the sidebar returns here instead of the overview redirect.
watch(
  () => [route.params.id, route.name],
  () => {
    const name = String(route.name || '')
    if (name.startsWith('project-') && route.params.id != null) {
      setLastProjectRoute(route.params.id, name)
    }
  },
  { immediate: true }
)

onMounted(loadProject)
watch(activeProject, current => {
  if (current?.id === ownId) project.value = { ...project.value, ...current }
})

// Phones: the header carries the project's name on every project screen.
// App.vue clears the title on each navigation (pre-flush); this re-applies
// it after, and follows a rename.
watch(
  () => [project.value?.name, route.fullPath],
  () => {
    if (!project.value || !String(route.name || '').startsWith('project-') || Number(route.params.id) !== ownId) return
    const section = contextSection(route.name)
    const label = { home: 'Home', browse: 'Assets', boards: 'Boards', chats: 'Chats', flows: 'Flows', 'all-tools': 'Tools' }[section] || 'Settings'
    setCompactTitle(label, project.value.name || 'Untitled project')
  },
  { immediate: true, flush: 'post' }
)
</script>
