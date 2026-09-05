<template>
  <div>
    <HeadlessServerBlock />
    <div class="mb-3">
      <div class="flex items-center gap-3">
        <h3 class="text-base font-medium text-content">Stimma Server</h3>
      </div>
      <p class="mt-1 max-w-xl text-xs leading-relaxed text-content-tertiary">
        Use this library and its tools from your other Stimma installs.
      </p>
    </div>

    <!-- Sign-in is disabled outright, so there is nothing to sign in to. -->
    <div v-if="privacyLockdownActive" class="mt-6 max-w-[680px] text-xs text-content-tertiary">
      Stimma Server needs a Stimma account, and Privacy Lockdown disables sign-in.
    </div>

    <!-- The section is always in the sidebar, signed in or not: a feature that
         only appears once you have signed in is one nobody discovers. Signed
         out, it says what it needs and where to get it. -->
    <div v-else-if="!user" class="mt-6 max-w-[680px]">
      <div class="flex items-center justify-between gap-6 py-2.5">
        <div class="min-w-0">
          <div class="text-[13px] text-content">Sign in to use Stimma Server</div>
          <div class="text-[11.5px] text-content-tertiary">
            Your other installs find this server through your Stimma account.
          </div>
        </div>
        <Button size="sm" @click="$emit('navigate', 'account')">Sign in</Button>
      </div>
    </div>

    <div v-else class="mt-6 max-w-[680px]">
      <MultiDeviceBlock />
    </div>
  </div>
</template>

<script setup>
import HeadlessServerBlock from './HeadlessServerBlock.vue'
import { useAuth } from '../../../composables/useAuth'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import Button from '../../ui/Button.vue'
import MultiDeviceBlock from './MultiDeviceBlock.vue'

defineEmits(['navigate'])

const { user } = useAuth()
const { privacyLockdownActive } = usePrivacyLockdown()
</script>
