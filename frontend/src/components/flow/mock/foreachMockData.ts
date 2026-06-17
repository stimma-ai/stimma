// Fake-data fixtures for ForeachGroupNode.vue preview — not wired to runtime.

export type MockStatus =
  | 'pending'
  | 'computing'
  | 'completed'
  | 'failed'
  | 'awaiting_input'
  | 'skipped'

export type MockNodeKind =
  | 'tool_call'
  | 'llm_call'
  | 'code'
  | 'hitl'
  | 'info'
  | 'flow_input'
  | 'flow_output'
  | 'control'
  | 'create_set'
  | 'create_grid'
  | 'create_document'

export interface MockBodyNode {
  id: string
  title: string
  subtitle?: string
  kind: MockNodeKind
  task_type?: string
  optional?: boolean
  iterStatuses: (MockStatus | null)[]
  iterDurations?: (number | null)[]
}

export interface MockForeachGroup {
  id: string
  header: string
  count: number
  iterLabels: string[]
  bodyNodes: MockBodyNode[]
}

const STATUSES: MockStatus[] = [
  'pending',
  'computing',
  'completed',
  'failed',
  'awaiting_input',
  'skipped',
]

function seeded(seed: number): () => number {
  let x = seed | 0
  return () => {
    x = (x * 1664525 + 1013904223) | 0
    return ((x >>> 0) % 1_000_000) / 1_000_000
  }
}

function pick<T>(rng: () => number, arr: readonly T[]): T {
  return arr[Math.floor(rng() * arr.length) % arr.length]
}

export function rollupIteration(
  bodyNodes: MockBodyNode[],
  i: number,
): MockStatus {
  let sawComputing = false
  let sawAwaiting = false
  let sawPending = false
  let allDoneOrSkipped = true
  for (const n of bodyNodes) {
    const s = n.iterStatuses[i]
    if (s === null || s === undefined) continue
    if (s === 'failed') return 'failed'
    if (s === 'awaiting_input') sawAwaiting = true
    else if (s === 'computing') sawComputing = true
    else if (s === 'pending') sawPending = true
    if (s !== 'completed' && s !== 'skipped') allDoneOrSkipped = false
  }
  if (sawAwaiting) return 'awaiting_input'
  if (sawComputing) return 'computing'
  if (sawPending) return 'pending'
  return allDoneOrSkipped ? 'completed' : 'pending'
}

export function aggregateCounts(
  statuses: (MockStatus | null)[],
): Record<MockStatus, number> {
  const counts: Record<MockStatus, number> = {
    pending: 0,
    computing: 0,
    completed: 0,
    failed: 0,
    awaiting_input: 0,
    skipped: 0,
  }
  for (const s of statuses) {
    if (s === null || s === undefined) continue
    counts[s] = (counts[s] ?? 0) + 1
  }
  return counts
}

// 40 iterations: 36 ok, 1 running, 3 failed. Upscale optional (30/40 present).
export function buildScenario40(): MockForeachGroup {
  const count = 40
  const rng = seeded(42)
  const iterLabels = Array.from({ length: count }, (_, i) =>
    `item ${String(i).padStart(3, '0')}`,
  )

  const promptStatuses: MockStatus[] = Array(count).fill('completed')
  const generateStatuses: (MockStatus | null)[] = Array(count).fill('completed')
  const refineStatuses: (MockStatus | null)[] = Array(count).fill('completed')
  const upscalePresent: boolean[] = Array.from({ length: count }, () => rng() > 0.25)
  const upscaleStatuses: (MockStatus | null)[] = upscalePresent.map((p) =>
    p ? 'completed' : null,
  )

  // Failures on a few iterations — cascade through downstream.
  const failIndices = [7, 17, 29]
  for (const i of failIndices) {
    generateStatuses[i] = 'failed'
    refineStatuses[i] = 'pending'
    if (upscalePresent[i]) upscaleStatuses[i] = 'pending'
  }

  // One iteration running mid-pipeline.
  const runningIdx = 23
  generateStatuses[runningIdx] = 'completed'
  refineStatuses[runningIdx] = 'computing'
  if (upscalePresent[runningIdx]) upscaleStatuses[runningIdx] = 'pending'

  // Durations for completed steps (ms).
  const dur = (status: MockStatus | null, fast = false): number | null =>
    status === 'completed'
      ? Math.round((fast ? 200 : 1500) + rng() * (fast ? 500 : 4500))
      : null

  return {
    id: 'foreach-40',
    header: 'foreach item in Items',
    count,
    iterLabels,
    bodyNodes: [
      {
        id: 'prompt',
        title: 'Prompt',
        kind: 'llm_call',
        iterStatuses: promptStatuses,
        iterDurations: promptStatuses.map((s) => dur(s, true)),
      },
      {
        id: 'generate',
        title: 'Generate',
        subtitle: 'text-to-image',
        kind: 'tool_call',
        task_type: 'text-to-image',
        iterStatuses: generateStatuses,
        iterDurations: generateStatuses.map((s) => dur(s)),
      },
      {
        id: 'refine',
        title: 'Refine',
        subtitle: 'image-to-image',
        kind: 'tool_call',
        task_type: 'image-to-image',
        iterStatuses: refineStatuses,
        iterDurations: refineStatuses.map((s) => dur(s)),
      },
      {
        id: 'upscale',
        title: 'Upscale',
        subtitle: 'upscale',
        kind: 'tool_call',
        task_type: 'upscale',
        optional: true,
        iterStatuses: upscaleStatuses,
        iterDurations: upscaleStatuses.map((s) => dur(s)),
      },
    ],
  }
}

// 400 iterations: stress-test degradation.
export function buildScenario400(): MockForeachGroup {
  const count = 400
  const rng = seeded(2026)
  const iterLabels = Array.from({ length: count }, (_, i) =>
    `item ${String(i).padStart(3, '0')}`,
  )

  const promptStatuses: MockStatus[] = Array(count).fill('completed')
  const generateStatuses: (MockStatus | null)[] = Array(count).fill('completed')
  const refineStatuses: (MockStatus | null)[] = Array(count).fill('completed')
  const upscalePresent: boolean[] = Array.from({ length: count }, () => rng() > 0.3)
  const upscaleStatuses: (MockStatus | null)[] = upscalePresent.map((p) =>
    p ? 'completed' : null,
  )

  // Sparse failures + a cluster of running.
  const failCount = 12
  for (let k = 0; k < failCount; k++) {
    const i = Math.floor(rng() * count)
    generateStatuses[i] = 'failed'
    refineStatuses[i] = 'pending'
    if (upscalePresent[i]) upscaleStatuses[i] = 'pending'
  }
  // A tail of iterations still running (last ~50 iterations still spinning).
  for (let i = count - 50; i < count; i++) {
    if (generateStatuses[i] === 'failed') continue
    if (rng() > 0.4) {
      refineStatuses[i] = 'computing'
      if (upscalePresent[i]) upscaleStatuses[i] = 'pending'
    } else if (rng() > 0.5) {
      refineStatuses[i] = 'pending'
      if (upscalePresent[i]) upscaleStatuses[i] = 'pending'
    }
  }

  const dur = (status: MockStatus | null, fast = false): number | null =>
    status === 'completed'
      ? Math.round((fast ? 200 : 1500) + rng() * (fast ? 500 : 4500))
      : null

  return {
    id: 'foreach-400',
    header: 'foreach prompt in Prompts',
    count,
    iterLabels,
    bodyNodes: [
      {
        id: 'prompt',
        title: 'Prompt',
        kind: 'llm_call',
        iterStatuses: promptStatuses,
        iterDurations: promptStatuses.map((s) => dur(s, true)),
      },
      {
        id: 'generate',
        title: 'Generate',
        subtitle: 'text-to-image',
        kind: 'tool_call',
        task_type: 'text-to-image',
        iterStatuses: generateStatuses,
        iterDurations: generateStatuses.map((s) => dur(s)),
      },
      {
        id: 'refine',
        title: 'Refine',
        subtitle: 'image-to-image',
        kind: 'tool_call',
        task_type: 'image-to-image',
        iterStatuses: refineStatuses,
        iterDurations: refineStatuses.map((s) => dur(s)),
      },
      {
        id: 'upscale',
        title: 'Upscale',
        subtitle: 'upscale',
        kind: 'tool_call',
        task_type: 'upscale',
        optional: true,
        iterStatuses: upscaleStatuses,
        iterDurations: upscaleStatuses.map((s) => dur(s)),
      },
    ],
  }
}

// 4 iterations: the "simple" end of the spectrum.
export function buildScenario4(): MockForeachGroup {
  const count = 4
  const iterLabels = ['Monet', 'Dali', 'Hokusai', 'Basquiat']
  const generateStatuses: MockStatus[] = ['completed', 'failed', 'computing', 'pending']
  const refineStatuses: (MockStatus | null)[] = ['completed', 'pending', 'pending', 'pending']

  return {
    id: 'foreach-4',
    header: 'foreach artist in artists',
    count,
    iterLabels,
    bodyNodes: [
      {
        id: 'prompt',
        title: 'Prompt',
        kind: 'llm_call',
        iterStatuses: ['completed', 'completed', 'completed', 'completed'],
        iterDurations: [340, 320, 410, 380],
      },
      {
        id: 'generate',
        title: 'Generate',
        subtitle: 'text-to-image',
        kind: 'tool_call',
        task_type: 'text-to-image',
        iterStatuses: generateStatuses,
        iterDurations: [3200, null, null, null],
      },
      {
        id: 'refine',
        title: 'Refine',
        subtitle: 'image-to-image',
        kind: 'tool_call',
        task_type: 'image-to-image',
        iterStatuses: refineStatuses,
        iterDurations: [4100, null, null, null],
      },
    ],
  }
}
