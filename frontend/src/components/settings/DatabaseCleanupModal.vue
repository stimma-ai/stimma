<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-modal flex items-center justify-center bg-overlay-backdrop p-4 backdrop-blur-sm"
      @click.self="close"
    >
      <div class="flex max-h-[90vh] w-[860px] max-w-[95vw] flex-col overflow-hidden rounded-lg border border-edge bg-surface shadow-2xl">
        <div class="flex items-start justify-between border-b border-edge px-6 py-4">
          <div>
            <h2 class="text-lg font-semibold text-content">Database maintenance</h2>
            <p class="mt-1 text-xs text-content-tertiary">Current profile only · foreign-key references only</p>
          </div>
          <button
            :disabled="busy"
            class="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-raised hover:text-content disabled:opacity-40"
            aria-label="Close database maintenance"
            @click="close"
          >
            <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto p-6">
          <div class="rounded-lg border border-edge-subtle bg-overlay-light p-4 text-sm text-content-secondary">
            <p>This tool analyzes historical SQLite foreign-key debris. Analysis is read-only and cleanup never runs automatically.</p>
            <p class="mt-2 text-xs text-content-tertiary">It does not delete Assets, Media, revisions, StorageObjects, managed files, or source files. It does not reconstruct lineage or run VACUUM.</p>
          </div>

          <div v-if="busy" class="flex min-h-32 items-center justify-center gap-3 text-content-tertiary">
            <svg class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4Z" />
            </svg>
            <div>
              <p class="text-sm text-content">{{ maintenance.phase === 'analyzing' ? 'Analyzing database…' : 'Cleaning orphaned references…' }}</p>
              <p class="mt-0.5 text-xs">Large profiles may take a while. Keep this window open.</p>
            </div>
          </div>

          <div v-else-if="maintenance.phase === 'error'" class="rounded-lg border border-red-500/50 bg-red-500/15 p-4">
            <p class="text-sm font-medium text-red-500">Database maintenance failed</p>
            <p class="mt-1 text-sm text-red-400">{{ maintenance.error }}</p>
            <p class="mt-2 text-xs text-content-tertiary">Cleanup failures are rolled back completely.</p>
          </div>

          <template v-else-if="maintenance.analysis">
            <div v-if="maintenance.result" class="rounded-lg border border-accent/50 bg-accent/15 p-4">
              <p class="text-sm font-medium text-accent">Cleanup complete</p>
              <p class="mt-1 text-sm text-content-secondary">
                Repaired {{ number(maintenance.result.repaired_count) }} of {{ number(maintenance.result.before.total_findings) }} findings.
                {{ number(maintenance.result.after.total_findings) }} remain report only.
              </p>
              <p class="mt-1 text-xs text-content-tertiary">
                {{ number(maintenance.result.deleted_count) }} child rows deleted · {{ number(maintenance.result.nullified_count) }} references cleared
              </p>
            </div>

            <div class="grid grid-cols-3 gap-3">
              <SummaryCard label="Total findings" :value="maintenance.analysis.total_findings" />
              <SummaryCard label="Repairable" :value="maintenance.analysis.repairable_count" tone="blue" />
              <SummaryCard label="Report only" :value="maintenance.analysis.report_only_count" tone="neutral" />
            </div>

            <div v-if="maintenance.analysis.total_findings === 0" class="rounded-lg bg-surface-raised/50 p-5 text-center text-sm text-content-secondary">
              No foreign-key violations found for this profile.
            </div>

            <div v-else class="overflow-hidden rounded-lg border border-edge">
              <div class="overflow-x-auto">
                <table class="w-full min-w-[760px] text-left text-xs">
                  <thead class="border-b border-edge bg-surface-raised text-content-tertiary">
                    <tr>
                      <th class="px-3 py-2 font-medium">Child reference</th>
                      <th class="px-3 py-2 font-medium">Missing parent</th>
                      <th class="px-3 py-2 font-medium">ON DELETE</th>
                      <th class="px-3 py-2 text-right font-medium">Count</th>
                      <th class="px-3 py-2 font-medium">Handling</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="group in maintenance.analysis.groups" :key="groupKey(group)" class="border-b border-edge/60 last:border-0">
                      <td class="px-3 py-3 font-mono text-content">{{ relationship(group.child_table, group.child_columns) }}</td>
                      <td class="px-3 py-3 font-mono text-content-secondary">{{ relationship(group.parent_table, group.parent_columns) }}</td>
                      <td class="px-3 py-3 text-content-secondary">{{ group.on_delete }}</td>
                      <td class="px-3 py-3 text-right text-content">{{ number(group.count) }}</td>
                      <td class="px-3 py-3">
                        <span
                          class="inline-flex rounded border px-2 py-0.5"
                          :class="group.repairable ? 'border-accent/50 bg-accent/15 text-accent' : 'border-edge-subtle bg-overlay-light text-content-tertiary'"
                        >
                          {{ findingHandlingLabel(group) }}
                        </span>
                        <p class="mt-1 max-w-[260px] text-content-tertiary">{{ group.reason }}</p>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>

          <div v-else class="py-5 text-center">
            <p class="text-sm text-content-secondary">Analyze the current profile to find orphaned foreign-key references.</p>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 border-t border-edge px-6 py-4">
          <button
            :disabled="busy"
            class="rounded-lg px-4 py-2 text-sm font-medium text-content-secondary transition-colors hover:bg-surface-raised hover:text-content disabled:opacity-40"
            @click="close"
          >
            Close
          </button>
          <button
            v-if="maintenance.analysis?.repairable_count > 0 && !maintenance.result"
            :disabled="busy"
            class="rounded-lg border border-red-500/50 bg-red-500/15 px-4 py-2 text-sm font-medium text-red-500 transition-colors hover:bg-red-500/20 disabled:opacity-40"
            @click="maintenance.requestCleanup()"
          >
            Clean orphaned references
          </button>
          <button
            :disabled="busy"
            class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            @click="maintenance.analyzeDatabase()"
          >
            {{ maintenance.analysis ? 'Analyze again' : 'Analyze database' }}
          </button>
        </div>
      </div>
    </div>

    <ConfirmModal
      :show="maintenance.showConfirmation"
      title="Clean orphaned references?"
      :message="confirmationMessage"
      confirm-text="Clean References"
      @confirm="maintenance.confirmCleanup()"
      @cancel="maintenance.cancelCleanup()"
    />
  </Teleport>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { useSettingsApi } from '../../composables/useSettingsApi'
import ConfirmModal from '../ConfirmModal.vue'
import SummaryCard from './DatabaseMaintenanceSummaryCard.vue'
import { createDatabaseCleanupController, findingHandlingLabel } from './databaseCleanupState'

const props = defineProps({
  show: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'cleaned'])
const { analyzeDatabaseMaintenance, cleanupDatabaseMaintenance } = useSettingsApi()
const maintenance = reactive(createDatabaseCleanupController({
  analyze: analyzeDatabaseMaintenance,
  cleanup: async () => {
    const result = await cleanupDatabaseMaintenance()
    emit('cleaned', result)
    return result
  },
}))

const busy = computed(() => ['analyzing', 'cleaning'].includes(maintenance.phase))
const confirmationMessage = computed(() =>
  `Repair ${number(maintenance.analysis?.repairable_count || 0)} orphaned references in the current profile?\n\n` +
  'CASCADE rows will be deleted and SET NULL references will be cleared in one transaction. Report-only findings will not be changed.'
)

watch(() => props.show, (open) => {
  if (open) {
    Object.assign(maintenance, {
      phase: 'idle',
      analysis: null,
      result: null,
      error: '',
      showConfirmation: false,
    })
  }
})

function close() {
  if (!busy.value) emit('close')
}

function number(value) {
  return Number(value || 0).toLocaleString()
}

function relationship(table, columns) {
  return `${table}.${columns?.length ? columns.join(', ') : '(unknown)'}`
}

function groupKey(group) {
  return [group.child_table, group.child_columns.join(','), group.parent_table, group.parent_columns.join(','), group.on_delete].join('|')
}
</script>
