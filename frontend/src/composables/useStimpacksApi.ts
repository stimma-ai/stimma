import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface SkillEnvironments {
  chat: boolean
  flow: boolean
  tool: boolean | { task_types: string[] }
}

export interface Skill {
  slug: string
  qualified_name: string
  display_name: string
  description: string
  environments: SkillEnvironments
  provides: string[]
  pack_name: string
  pack_display_name: string
}

export interface Stimpack {
  name: string
  display_name: string
  description: string
  author: string
  tags: string[]
  tier: 'local' | 'marketplace'
  source: 'profile' | 'dev'
  is_dev: boolean
  marketplace_version: number | null
  marketplace_author: string | null
  marketplace_author_avatar_key: string | null
  skills: Skill[]
}

export interface StimpackDetail extends Stimpack {
  content: string
}

export interface StimpackCreateRequest {
  name: string
  display_name?: string
  description?: string
  tags?: string[]
  content: string
}

export interface StimpackUpdateRequest {
  display_name?: string | null
  description?: string | null
  tags?: string[] | null
  content?: string | null
}

// Marketplace types
export interface MarketplaceStimpack {
  id: string
  name: string
  displayName: string
  shortDescription: string
  tags: string[]
  hasLib: boolean
  nsfw: boolean
  autoInstall: boolean
  installCount: number
  currentVersion: number | null
  currentVersionId: string | null
  createdAt: string
  updatedAt: string
  authorUsername: string | null
  authorAvatarKey: string | null
}

export interface MarketplaceStimpackDetail extends MarketplaceStimpack {
  versions: Array<{
    id: string
    version: number
    changelog: string | null
    hasLib: boolean
    nsfw: boolean
    fileSizeBytes: number
    createdAt: string
  }>
  skillMdText: string | null
}

export interface MarketplaceListResponse {
  stimpacks: MarketplaceStimpack[]
  total: number
  page: number
  limit: number
  pages: number
}

export function useStimpacksApi() {
  const base = () => `${getApiBase()}/settings/stimpacks`
  const marketplaceBase = () => `${getApiBase()}/stimpack-marketplace`

  // --- Local stimpack management (existing) ---

  async function listStimpacks(): Promise<Stimpack[]> {
    const response = await axios.get(base())
    return response.data
  }

  // --- Flat skills (the agent-facing units inside stimpacks) ---

  async function listSkills(): Promise<Skill[]> {
    const response = await axios.get(`${getApiBase()}/settings/skills`)
    return response.data
  }

  async function getSkillContent(qualifiedName: string): Promise<{ qualified_name: string; display_name: string; content: string }> {
    // Qualified names contain '/' and the backend route takes a path param —
    // encode each segment but keep the separators.
    const path = qualifiedName.split('/').map(encodeURIComponent).join('/')
    const response = await axios.get(`${getApiBase()}/settings/skills/${path}/content`)
    return response.data
  }

  /** True if a skill is eligible for a tool with the given task types. */
  function skillEligibleForTool(skill: Skill, taskTypes: string[]): boolean {
    const tool = skill.environments?.tool
    if (tool === true) return true
    if (tool && typeof tool === 'object' && Array.isArray(tool.task_types)) {
      return tool.task_types.some(t => taskTypes.includes(t))
    }
    return false
  }

  async function getStimpack(name: string): Promise<StimpackDetail> {
    const response = await axios.get(`${base()}/${encodeURIComponent(name)}`)
    return response.data
  }

  async function createStimpack(data: StimpackCreateRequest): Promise<StimpackDetail> {
    const response = await axios.post(base(), data)
    return response.data
  }

  async function updateStimpack(name: string, data: StimpackUpdateRequest): Promise<StimpackDetail> {
    const response = await axios.put(`${base()}/${encodeURIComponent(name)}`, data)
    return response.data
  }

  async function deleteStimpack(name: string): Promise<void> {
    await axios.delete(`${base()}/${encodeURIComponent(name)}`)
  }

  async function uploadStimpack(file: File): Promise<Stimpack> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await axios.post(`${base()}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  // --- Marketplace ---

  async function browseMarketplace(params?: {
    q?: string
    tags?: string[]
    sort?: 'popular' | 'recent' | 'updated'
    nsfw?: boolean
    page?: number
    limit?: number
  }): Promise<MarketplaceListResponse> {
    const query = new URLSearchParams()
    if (params?.q) query.set('q', params.q)
    if (params?.tags?.length) query.set('tags', params.tags.join(','))
    if (params?.sort) query.set('sort', params.sort)
    if (params?.nsfw) query.set('nsfw', 'true')
    if (params?.page) query.set('page', String(params.page))
    if (params?.limit) query.set('limit', String(params.limit))
    const response = await axios.get(`${marketplaceBase()}/browse?${query.toString()}`)
    return response.data
  }

  async function getMarketplaceStimpack(name: string): Promise<MarketplaceStimpackDetail> {
    const response = await axios.get(`${marketplaceBase()}/detail/${encodeURIComponent(name)}`)
    return response.data
  }

  async function installFromMarketplace(name: string): Promise<Stimpack> {
    const response = await axios.post(`${marketplaceBase()}/install/${encodeURIComponent(name)}`)
    return response.data
  }

  async function runAutoInstall(): Promise<{ installed: string[]; failed?: string[]; message?: string }> {
    const response = await axios.post(`${marketplaceBase()}/auto-install`)
    return response.data
  }

  async function checkUpdates(): Promise<Array<{ name: string; newVersion: number; versionId: string }>> {
    const response = await axios.get(`${marketplaceBase()}/check-updates`)
    return response.data.updates || []
  }

  async function updateFromMarketplace(name: string): Promise<Stimpack> {
    const response = await axios.post(`${marketplaceBase()}/update/${encodeURIComponent(name)}`)
    return response.data
  }

  async function listMyMarketplaceStimpacks(): Promise<{ stimpacks: Array<MarketplaceStimpack & { latestVersion: { version: number; status: string } | null }> }> {
    const response = await axios.get(`${marketplaceBase()}/mine`)
    return response.data
  }

  return {
    // Local
    listStimpacks,
    getStimpack,
    createStimpack,
    updateStimpack,
    deleteStimpack,
    uploadStimpack,
    // Skills (flat)
    listSkills,
    getSkillContent,
    skillEligibleForTool,
    // Marketplace
    browseMarketplace,
    getMarketplaceStimpack,
    installFromMarketplace,
    runAutoInstall,
    checkUpdates,
    updateFromMarketplace,
    listMyMarketplaceStimpacks,
  }
}
