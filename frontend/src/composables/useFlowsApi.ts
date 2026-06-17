import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface Flow {
  id: number
  name: string
  description?: string | null
  parent_id?: number | null
  project_id?: number | null
  input_schema?: Record<string, any> | null
  output_schema?: Record<string, any> | null
  inputs?: Record<string, any> | null
  program_hash?: string | null
  execution_state: 'idle' | 'running' | 'paused'
  pending_task_count?: number
  root_status_summary?: Record<string, number>
  has_load_error?: boolean
  created_at: string
  updated_at: string
  deleted_at?: string | null
}

export interface FlowTask {
  task_id: string
  task_type: 'select' | 'approve' | 'error' | 'waiting_for_tool'
  status: 'pending' | 'resolved' | 'cancelled'
  instructions?: string | null
  payload?: Record<string, any> | null
  resolution?: any
  created_at: string
  resolved_at?: string | null
  equation_key: string
  equation_type: string
  equation_status: string
  phase_path: string[]
  inputs_hash?: string | null
  attempt: number
  error?: string | null
  dependencies: string[]
  downstream_count: number
  flow_id?: number | null
  flow_name?: string | null
}

export interface FlowEquation {
  equation_key: string
  equation_type: string
  status: string
  display_name?: string | null
  phase_path: string[]
  inputs_hash?: string | null
  attempt: number
  result?: any
  result_media_ids: number[]
  execution_duration_ms?: number | null
  // Tool-reported pure compute time (from MediaItem.generation_metadata) —
  // present for tool_call equations that produced media. Prefer over
  // execution_duration_ms when showing per-iteration "how long did this
  // image take to generate"; wall-clock (execution_duration_ms) still feeds
  // phase/group rollups where the user-waited envelope is the right number.
  compute_duration_ms?: number | null
  error?: string | null
  dependencies: string[]
  created_at?: string | null
  completed_at?: string | null
  invalidated_at?: string | null
  is_scaffolding?: boolean
  hitl_kind?: string | null
  hitl_count?: number | null
  tool_id?: string | null
  task_type?: string | null
  control_kind?: string | null
  result_from?: string | null
  description?: string | null
  subtitle?: string | null
  routing_kind?: string | null
  is_output?: boolean
  output_name?: string | null
  output_type?: string | null
  // hitl.approve primitives only — declared count and approval instructions
  // strip, surfaced explicitly so SlotGroup can render without reading
  // raw definition JSON.
  slot_count?: number | null
  instructions?: string | null
  // flow_input only — the schema field key (definition.input_name). Lets
  // the Workflow inspect panel scope its editable input form to the matching
  // schema field, so selecting an input node offers the same edit affordance
  // the steps-view input card already provides.
  input_name?: string | null
}

export interface PhaseNode {
  name: string
  path: string[]
  children: PhaseNode[]
  equation_keys: string[]
  steps?: any[]
  status_summary: Record<string, number>
  pending_task_count: number
}

export interface PhaseTree {
  flow_id: number
  execution_state: string
  root: PhaseNode
  load_error?: {
    category: string
    message: string
    suggestion?: string | null
    program_traceback?: string | null
    issues?: Array<{
      equation_key: string
      equation_type: string
      status: string
      message: string
      category: string
      phase_path: string[]
    }> | null
  } | null
}

function base() { return getApiBase() }

export function useFlowsApi() {
  async function listFlows(params: {
    execution_state?: string
    project_id?: number
    parent_id?: number
    include_deleted?: boolean
  } = {}): Promise<Flow[]> {
    const response = await axios.get(`${base()}/flows`, { params })
    return response.data
  }

  async function getFlow(id: number | string): Promise<Flow> {
    const response = await axios.get(`${base()}/flows/${id}`)
    return response.data
  }

  async function createFlow(body: Partial<Flow> = {}): Promise<Flow> {
    const response = await axios.post(`${base()}/flows`, body)
    return response.data
  }

  async function updateFlow(id: number | string, body: Partial<Flow>): Promise<Flow> {
    const response = await axios.patch(`${base()}/flows/${id}`, body)
    return response.data
  }

  async function deleteFlow(id: number | string): Promise<void> {
    await axios.delete(`${base()}/flows/${id}`)
  }

  async function restoreFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/restore`)
    return response.data
  }

  async function forkFlow(id: number | string, body: {
    name?: string
    inputs?: Record<string, any>
    project_id?: number
  } = {}): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/fork`, body)
    return response.data
  }

  async function startFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/start`)
    return response.data
  }

  async function pauseFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/pause`)
    return response.data
  }

  async function resumeFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/resume`)
    return response.data
  }

  async function clearFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/clear`)
    return response.data
  }

  async function reparseFlow(id: number | string): Promise<Flow> {
    const response = await axios.post(`${base()}/flows/${id}/reparse`)
    return response.data
  }

  async function getPhaseTree(id: number | string): Promise<PhaseTree> {
    const response = await axios.get(`${base()}/flows/${id}/phases`)
    return response.data
  }

  async function listEquations(id: number | string, params: {
    status?: string
    phase_path?: string[]
  } = {}): Promise<FlowEquation[]> {
    const query: Record<string, any> = {}
    if (params.status) query.status = params.status
    if (params.phase_path) query.phase_path = JSON.stringify(params.phase_path)
    const response = await axios.get(`${base()}/flows/${id}/equations`, { params: query })
    return response.data
  }

  async function getEquation(id: number | string, equationKey: string): Promise<FlowEquation> {
    const response = await axios.get(`${base()}/flows/${id}/equations/${encodeURIComponent(equationKey)}`)
    return response.data
  }

  async function listFlowTasks(id: number | string, params: {
    sort?: string
    task_type?: string
    status?: string
  } = {}): Promise<FlowTask[]> {
    const response = await axios.get(`${base()}/flows/${id}/tasks`, { params })
    return response.data
  }

  async function resolveTask(taskId: string, body: {
    resolution?: any
    action?: string
    value?: any
  }): Promise<FlowTask> {
    const response = await axios.post(`${base()}/tasks/${encodeURIComponent(taskId)}/resolve`, body)
    return response.data
  }

  async function invalidateEquation(flowId: number | string, equationKey: string): Promise<any> {
    const response = await axios.post(`${base()}/flows/${flowId}/equations/${encodeURIComponent(equationKey)}/invalidate`)
    return response.data
  }

  async function reselectEquation(
    flowId: number | string,
    equationKey: string,
    resolution: any,
  ): Promise<any> {
    const response = await axios.post(
      `${base()}/flows/${flowId}/equations/${encodeURIComponent(equationKey)}/reselect`,
      { resolution },
    )
    return response.data
  }

  async function invalidatePhase(flowId: number | string, phasePath: string[]): Promise<any> {
    const response = await axios.post(`${base()}/flows/${flowId}/phases/invalidate`, { phase_path: phasePath })
    return response.data
  }

  async function getProgramCode(id: number | string): Promise<string> {
    const response = await axios.get(`${base()}/flows/${id}/program`)
    return response.data.code ?? ''
  }

  async function updateProgramCode(
    id: number | string,
    code: string,
  ): Promise<{ code: string; load_error: any }> {
    const response = await axios.put(`${base()}/flows/${id}/program`, { code })
    return response.data
  }

  return {
    listFlows,
    getFlow,
    createFlow,
    updateFlow,
    deleteFlow,
    restoreFlow,
    forkFlow,
    startFlow,
    pauseFlow,
    resumeFlow,
    clearFlow,
    reparseFlow,
    getPhaseTree,
    listEquations,
    getEquation,
    listFlowTasks,
    resolveTask,
    invalidateEquation,
    reselectEquation,
    invalidatePhase,
    getProgramCode,
    updateProgramCode,
  }
}
