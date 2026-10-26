import { initApiConfig } from '../../src/apiConfig'
import { useAppUpdater } from '../../src/composables/useAppUpdater'
import { useMultiDevice } from '../../src/composables/useMultiDevice'
import { startServerUpdater, stopServerUpdater, useServerUpdater } from '../../src/composables/useServerUpdater'

const updater = useServerUpdater()

Object.assign(window, {
  serverUpdater: {
    async start() {
      await initApiConfig()
      await useMultiDevice().init()
      startServerUpdater()
    },
    stop: stopServerUpdater,
    // The browser has no client updater; let the follow-up stage run its check.
    clientUpdaterReady() { useAppUpdater().loadedPrefs.value = true },
    act: updater.act,
    snapshot: () => ({
      pending: updater.pending.value ? { ...updater.pending.value } : null,
      version: updater.server.value?.version ?? null,
      status: updater.server.value?.status ?? null,
      busy: updater.serverBusy.value,
    }),
  },
})
