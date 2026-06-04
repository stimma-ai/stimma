import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface Recipe {
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

export interface RecipeTask {
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
  recipe_id?: number | null
  recipe_name?: string | null
}

export interface RecipeEquation {
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
  // recipe_input only — the schema field key (definition.input_name). Lets
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
  recipe_id: number
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

export function useRecipesApi() {
  async function listRecipes(params: {
    execution_state?: string
    project_id?: number
    parent_id?: number
    include_deleted?: boolean
  } = {}): Promise<Recipe[]> {
    const response = await axios.get(`${base()}/recipes`, { params })
    return response.data
  }

  async function getRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.get(`${base()}/recipes/${id}`)
    return response.data
  }

  async function createRecipe(body: Partial<Recipe> = {}): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes`, body)
    return response.data
  }

  async function updateRecipe(id: number | string, body: Partial<Recipe>): Promise<Recipe> {
    const response = await axios.patch(`${base()}/recipes/${id}`, body)
    return response.data
  }

  async function deleteRecipe(id: number | string): Promise<void> {
    await axios.delete(`${base()}/recipes/${id}`)
  }

  async function restoreRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/restore`)
    return response.data
  }

  async function forkRecipe(id: number | string, body: {
    name?: string
    inputs?: Record<string, any>
    project_id?: number
  } = {}): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/fork`, body)
    return response.data
  }

  async function startRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/start`)
    return response.data
  }

  async function pauseRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/pause`)
    return response.data
  }

  async function resumeRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/resume`)
    return response.data
  }

  async function clearRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/clear`)
    return response.data
  }

  async function reparseRecipe(id: number | string): Promise<Recipe> {
    const response = await axios.post(`${base()}/recipes/${id}/reparse`)
    return response.data
  }

  async function getPhaseTree(id: number | string): Promise<PhaseTree> {
    const response = await axios.get(`${base()}/recipes/${id}/phases`)
    return response.data
  }

  async function listEquations(id: number | string, params: {
    status?: string
    phase_path?: string[]
  } = {}): Promise<RecipeEquation[]> {
    const query: Record<string, any> = {}
    if (params.status) query.status = params.status
    if (params.phase_path) query.phase_path = JSON.stringify(params.phase_path)
    const response = await axios.get(`${base()}/recipes/${id}/equations`, { params: query })
    return response.data
  }

  async function getEquation(id: number | string, equationKey: string): Promise<RecipeEquation> {
    const response = await axios.get(`${base()}/recipes/${id}/equations/${encodeURIComponent(equationKey)}`)
    return response.data
  }

  async function listRecipeTasks(id: number | string, params: {
    sort?: string
    task_type?: string
    status?: string
  } = {}): Promise<RecipeTask[]> {
    const response = await axios.get(`${base()}/recipes/${id}/tasks`, { params })
    return response.data
  }

  async function resolveTask(taskId: string, body: {
    resolution?: any
    action?: string
    value?: any
  }): Promise<RecipeTask> {
    const response = await axios.post(`${base()}/tasks/${encodeURIComponent(taskId)}/resolve`, body)
    return response.data
  }

  async function invalidateEquation(recipeId: number | string, equationKey: string): Promise<any> {
    const response = await axios.post(`${base()}/recipes/${recipeId}/equations/${encodeURIComponent(equationKey)}/invalidate`)
    return response.data
  }

  async function reselectEquation(
    recipeId: number | string,
    equationKey: string,
    resolution: any,
  ): Promise<any> {
    const response = await axios.post(
      `${base()}/recipes/${recipeId}/equations/${encodeURIComponent(equationKey)}/reselect`,
      { resolution },
    )
    return response.data
  }

  async function invalidatePhase(recipeId: number | string, phasePath: string[]): Promise<any> {
    const response = await axios.post(`${base()}/recipes/${recipeId}/phases/invalidate`, { phase_path: phasePath })
    return response.data
  }

  async function getProgramCode(id: number | string): Promise<string> {
    const response = await axios.get(`${base()}/recipes/${id}/program`)
    return response.data.code ?? ''
  }

  async function updateProgramCode(
    id: number | string,
    code: string,
  ): Promise<{ code: string; load_error: any }> {
    const response = await axios.put(`${base()}/recipes/${id}/program`, { code })
    return response.data
  }

  return {
    listRecipes,
    getRecipe,
    createRecipe,
    updateRecipe,
    deleteRecipe,
    restoreRecipe,
    forkRecipe,
    startRecipe,
    pauseRecipe,
    resumeRecipe,
    clearRecipe,
    reparseRecipe,
    getPhaseTree,
    listEquations,
    getEquation,
    listRecipeTasks,
    resolveTask,
    invalidateEquation,
    reselectEquation,
    invalidatePhase,
    getProgramCode,
    updateProgramCode,
  }
}
