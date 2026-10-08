import { computed, inject, provide, unref, type ComputedRef, type InjectionKey, type Ref } from 'vue'
import { useWorkingContext } from './useWorkingContext'
import { resolveProjectId, type ProjectId } from '../utils/projectScope'

type ProjectSource = Ref<ProjectId | undefined> | ComputedRef<ProjectId | undefined>

/**
 * The project that owns a subtree of the UI (a tool tab, a chat). Uploads and
 * other new assets created inside it land in this project even when the active
 * working project differs, for example while a kept-alive tab finishes work.
 */
export const OWNER_PROJECT_KEY: InjectionKey<ProjectSource> = Symbol('ownerProject')

export function provideOwnerProject(source: ProjectSource) {
  provide(OWNER_PROJECT_KEY, source)
}

/**
 * Resolves the project for new assets: an explicit value, else the nearest
 * provided owner, else the active working project.
 */
export function useOwnerProject(explicit?: () => ProjectId | undefined): ComputedRef<ProjectId> {
  const owner = inject(OWNER_PROJECT_KEY, null)
  const { activeProjectId } = useWorkingContext()
  return computed(() => resolveProjectId(
    explicit?.(),
    owner ? unref(owner) : undefined,
    activeProjectId.value,
  ))
}
