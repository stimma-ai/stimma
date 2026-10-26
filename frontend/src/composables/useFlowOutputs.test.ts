import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { computeFlowOutputs } from './useFlowOutputs.ts'
import type { FlowEquation } from './useFlowsApi.ts'

// Shared with the backend, which picks the same outputs for Home's previews.
const vectors = JSON.parse(readFileSync(new URL('../../../backend/tests/fixtures/flow_output_vectors.json', import.meta.url), 'utf8'))

for (const vector of vectors.cases) {
  test(`flow outputs: ${vector.name}`, () => {
    const byKey = new Map<string, FlowEquation>()
    for (const eq of vector.equations) {
      byKey.set(eq.equation_key, { is_output: false, is_scaffolding: false, result_media_ids: [], ...eq } as FlowEquation)
    }
    assert.deepEqual(computeFlowOutputs(byKey).map(output => output.mediaId), vector.expected)
  })
}
