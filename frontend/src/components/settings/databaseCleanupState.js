export function errorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

export function findingHandlingLabel(group) {
  if (!group?.repairable) return 'Report only'
  return group.repair_action === 'delete_child' ? 'Delete child' : 'Clear reference'
}

export function createDatabaseCleanupController({ analyze, cleanup }) {
  return {
    phase: 'idle',
    analysis: null,
    result: null,
    error: '',
    showConfirmation: false,

    async analyzeDatabase() {
      this.phase = 'analyzing'
      this.error = ''
      this.result = null
      try {
        this.analysis = await analyze()
        this.phase = 'results'
      } catch (error) {
        this.error = errorMessage(error, 'Failed to analyze database')
        this.phase = 'error'
      }
    },

    requestCleanup() {
      if ((this.analysis?.repairable_count || 0) > 0) {
        this.showConfirmation = true
      }
    },

    cancelCleanup() {
      this.showConfirmation = false
    },

    async confirmCleanup() {
      this.showConfirmation = false
      this.phase = 'cleaning'
      this.error = ''
      try {
        this.result = await cleanup()
        this.analysis = this.result.after
        this.phase = 'results'
      } catch (error) {
        this.error = errorMessage(error, 'Database cleanup failed')
        this.phase = 'error'
      }
    },
  }
}
