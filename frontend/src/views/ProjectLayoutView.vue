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
import { useRoute } from 'vue-router'
import { useMediaApi } from '../composables/useMediaApi'
import { useProjectRoute } from '../composables/useProjectRoute'

const route = useRoute()
const { getProject } = useMediaApi()
const { setLastProjectRoute } = useProjectRoute()

const project = ref(null)

provide('projectRef', project)

async function loadProject() {
  project.value = await getProject(route.params.id)
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
watch(() => route.params.id, loadProject)
</script>
