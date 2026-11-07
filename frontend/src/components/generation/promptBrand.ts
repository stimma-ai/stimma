import { computed } from 'vue'
import { appBranchRef } from '../../appConfig'

/** The name of Tool View's prompt feature (reads the prompt once, varies it every image).
    Change it here; every user-facing string uses this. */
export const PROMPT_BRAND = 'Fluent'

/** Fluent (and its Direct and Raw modes) ships in dev and canary builds only, for now.
    Elsewhere Tool View is exactly the classic Enhance prompt card: no prompt menu, no
    Raw or Direct, no prepared programs, and settings saved by a canary build are
    ignored. Flip this to widen the rollout. */
export const fluentEnabled = computed(() => appBranchRef.value === 'dev' || appBranchRef.value === 'canary')
