import axios from 'axios'
import { getApiBase } from '../apiConfig'

export interface Skill {
  name: string
  display_name: string
  description: string
  author: string
  tags: string[]
  tier: 'local' | 'marketplace'
  marketplace_version: number | null
  marketplace_author: string | null
  marketplace_author_avatar_key: string | null
}

export interface SkillDetail extends Skill {
  content: string
}

export interface SkillCreateRequest {
  name: string
  display_name?: string
  description?: string
  tags?: string[]
  content: string
}

export interface SkillUpdateRequest {
  display_name?: string | null
  description?: string | null
  tags?: string[] | null
  content?: string | null
}

// Marketplace types
export interface MarketplaceSkill {
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

export interface MarketplaceSkillDetail extends MarketplaceSkill {
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
  skills: MarketplaceSkill[]
  total: number
  page: number
  limit: number
  pages: number
}

export function useSkillsApi() {
  const base = () => `${getApiBase()}/settings/skills`
  const marketplaceBase = () => `${getApiBase()}/skill-marketplace`

  // --- Local skill management (existing) ---

  async function listSkills(): Promise<Skill[]> {
    const response = await axios.get(base())
    return response.data
  }

  async function getSkill(name: string): Promise<SkillDetail> {
    const response = await axios.get(`${base()}/${encodeURIComponent(name)}`)
    return response.data
  }

  async function createSkill(data: SkillCreateRequest): Promise<SkillDetail> {
    const response = await axios.post(base(), data)
    return response.data
  }

  async function updateSkill(name: string, data: SkillUpdateRequest): Promise<SkillDetail> {
    const response = await axios.put(`${base()}/${encodeURIComponent(name)}`, data)
    return response.data
  }

  async function deleteSkill(name: string): Promise<void> {
    await axios.delete(`${base()}/${encodeURIComponent(name)}`)
  }

  async function uploadSkill(file: File): Promise<Skill> {
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

  async function getMarketplaceSkill(name: string): Promise<MarketplaceSkillDetail> {
    const response = await axios.get(`${marketplaceBase()}/detail/${encodeURIComponent(name)}`)
    return response.data
  }

  async function installFromMarketplace(name: string): Promise<Skill> {
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

  async function updateFromMarketplace(name: string): Promise<Skill> {
    const response = await axios.post(`${marketplaceBase()}/update/${encodeURIComponent(name)}`)
    return response.data
  }

  async function listMyMarketplaceSkills(): Promise<{ skills: Array<MarketplaceSkill & { latestVersion: { version: number; status: string } | null }> }> {
    const response = await axios.get(`${marketplaceBase()}/mine`)
    return response.data
  }

  return {
    // Local
    listSkills,
    getSkill,
    createSkill,
    updateSkill,
    deleteSkill,
    uploadSkill,
    // Marketplace
    browseMarketplace,
    getMarketplaceSkill,
    installFromMarketplace,
    runAutoInstall,
    checkUpdates,
    updateFromMarketplace,
    listMyMarketplaceSkills,
  }
}
