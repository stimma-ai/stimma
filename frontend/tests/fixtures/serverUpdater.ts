import { initApiConfig } from '../../src/apiConfig'
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
    act: updater.act,
    snapshot: () => ({
      pending: updater.pending.value ? { ...updater.pending.value } : null,
      version: updater.server.value?.version ?? null,
      status: updater.server.value?.status ?? null,
      busy: updater.serverBusy.value,
    }),
  },
})
