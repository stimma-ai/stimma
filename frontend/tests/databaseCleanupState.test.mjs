import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createDatabaseCleanupController,
  findingHandlingLabel,
} from '../src/components/settings/databaseCleanupState.js'

const analysis = {
  profile_id: 'default',
  total_findings: 4,
  repairable_count: 3,
  report_only_count: 1,
  groups: [
    { child_table: 'faces', repairable: true, repair_action: 'delete_child', count: 2 },
    { child_table: 'lineage', repairable: true, repair_action: 'set_null', count: 1 },
    { child_table: 'memberships', repairable: false, repair_action: null, count: 1 },
  ],
}

test('analyze loads grouped repairable and report-only findings', async () => {
  const controller = createDatabaseCleanupController({
    analyze: async () => analysis,
    cleanup: async () => assert.fail('cleanup should not run'),
  })

  const pending = controller.analyzeDatabase()
  assert.equal(controller.phase, 'analyzing')
  await pending

  assert.equal(controller.phase, 'results')
  assert.equal(controller.analysis, analysis)
  assert.equal(controller.analysis.repairable_count, 3)
  assert.equal(controller.analysis.report_only_count, 1)
  assert.equal(findingHandlingLabel(analysis.groups[0]), 'Delete child')
  assert.equal(findingHandlingLabel(analysis.groups[1]), 'Clear reference')
  assert.equal(findingHandlingLabel(analysis.groups[2]), 'Report only')
})

test('cleanup requires a separate confirmation before invoking the API', async () => {
  let cleanupCalls = 0
  const controller = createDatabaseCleanupController({
    analyze: async () => analysis,
    cleanup: async () => {
      cleanupCalls += 1
      return { before: analysis, after: { ...analysis, total_findings: 1, repairable_count: 0 }, repaired_count: 3 }
    },
  })
  await controller.analyzeDatabase()

  controller.requestCleanup()
  assert.equal(controller.showConfirmation, true)
  assert.equal(cleanupCalls, 0)
  controller.cancelCleanup()
  assert.equal(controller.showConfirmation, false)

  controller.requestCleanup()
  await controller.confirmCleanup()
  assert.equal(cleanupCalls, 1)
})

test('successful cleanup presents the rerun analysis and before/after result', async () => {
  const after = { ...analysis, total_findings: 1, repairable_count: 0, report_only_count: 1 }
  const result = { before: analysis, after, repaired_count: 3, deleted_count: 2, nullified_count: 1 }
  const controller = createDatabaseCleanupController({
    analyze: async () => analysis,
    cleanup: async () => result,
  })
  await controller.analyzeDatabase()
  controller.requestCleanup()
  await controller.confirmCleanup()

  assert.equal(controller.phase, 'results')
  assert.equal(controller.result, result)
  assert.equal(controller.analysis, after)
  assert.equal(controller.analysis.report_only_count, 1)
})

test('analyze and cleanup failures expose backend detail', async () => {
  const analyzeFailure = createDatabaseCleanupController({
    analyze: async () => { throw new Error('scan unavailable') },
    cleanup: async () => {},
  })
  await analyzeFailure.analyzeDatabase()
  assert.equal(analyzeFailure.phase, 'error')
  assert.equal(analyzeFailure.error, 'scan unavailable')

  const cleanupFailure = createDatabaseCleanupController({
    analyze: async () => analysis,
    cleanup: async () => {
      throw { response: { data: { detail: 'all changes were rolled back' } } }
    },
  })
  await cleanupFailure.analyzeDatabase()
  cleanupFailure.requestCleanup()
  await cleanupFailure.confirmCleanup()
  assert.equal(cleanupFailure.phase, 'error')
  assert.equal(cleanupFailure.error, 'all changes were rolled back')
  assert.equal(cleanupFailure.analysis, analysis)
})
