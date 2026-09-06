import { computed, ref, watch } from 'vue'

/** Transport recovery must not unmount an established mobile workspace. */
export function useConnectionPresentation(connectionState, activeDeviceId, shellKind) {
  const establishedDevice = ref(null)
  watch([activeDeviceId, connectionState], ([device, state], previous) => {
    if (device !== previous?.[0]) establishedDevice.value = null
    if (state === 'ready') establishedDevice.value = device
  }, { immediate: true, flush: 'sync' })

  const showConnectionScreen = computed(() => {
    if (connectionState.value === 'ready') return false
    const mobile = shellKind === 'ios' || shellKind === 'android'
    return !(mobile && establishedDevice.value !== null && establishedDevice.value === activeDeviceId.value)
  })

  return { showConnectionScreen }
}
