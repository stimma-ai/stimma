import {
  syncedStorage,
  handleWorkspaceEvent,
  isServerMode,
  getDoc,
  flushWorkspace,
  rehydrate,
  detachProfile,
} from '../../src/utils/workspaceStore'
import { activateWorkspace, collectLocalWorkspace } from '../../src/utils/workspaceBoot'
import { setAppModifier } from '../../src/appConfig'
import { setCurrentProfileId } from '../../src/composables/useProfile'
Object.assign(window, {
  workspace: {
    syncedStorage,
    handleWorkspaceEvent,
    isServerMode,
    getDoc,
    flushWorkspace,
    rehydrate,
    detachProfile,
    activateWorkspace,
    collectLocalWorkspace,
    setAppModifier,
    setCurrentProfileId,
  },
})
