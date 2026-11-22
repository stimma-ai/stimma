// Per-profile state across an in-place profile switch (web and phones switch in
// the same window), driven against a stubbed server that answers per profile.
import { activateWorkspace } from '../../src/utils/workspaceBoot'
import { getDoc, handleWorkspaceEvent } from '../../src/utils/workspaceStore'
import { loadProfiles, setCurrentProfileId } from '../../src/composables/useProfile'
import { useToolAutoDeleteDuration } from '../../src/composables/useToolAutoDeleteDuration'
import { useMarkers } from '../../src/composables/useMarkers'
import { applyCloudAccount, fetchCloudAccount, getCloudUser } from '../../src/composables/useCloudAccount'

// A module-level listener registered before the workspace is, as the tab and
// dock modules are: it must find the old profile already detached.
const seenOnSwitch: unknown[] = []
window.addEventListener('profile-changed', () => {
  seenOnSwitch.push(getDoc('kv', 'tool_auto_delete_duration') ?? null)
})

Object.assign(window, {
  t: {
    activateWorkspace,
    handleWorkspaceEvent,
    loadProfiles,
    setCurrentProfileId,
    autoDelete: useToolAutoDeleteDuration(),
    markers: useMarkers(),
    applyCloudAccount,
    fetchCloudAccount,
    getCloudUser,
    seenOnSwitch,
  },
})
