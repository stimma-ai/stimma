/**
 * Agent Settings API composable
 * Handles API calls for per-chat agent settings management
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'

function getChatsAPIBase() {
  return `${getApiBase()}/chats`
}

/**
 * Tool configuration for agent settings
 */
export interface ToolConfig {
  allowed_tools: string[]
  denied_tools: string[]
  v2_permissions?: Record<string, string> // V2 tool permissions: tool_name -> "allow" | "deny"
  enabled_skills?: string[]
}

/**
 * Agent settings for a chat
 */
export interface AgentSettings {
  additional_instructions: string | null
  tool_config: ToolConfig | null
}

/**
 * Request for updating chat agent settings
 */
export interface AgentSettingsUpdateRequest {
  additional_instructions?: string | null
  tool_config?: ToolConfig | null
}

export function useAgentPresetsApi() {
  /**
   * Get agent settings for a chat
   */
  async function getChatAgentSettings(chatId: number): Promise<AgentSettings> {
    const response = await axios.get(`${getChatsAPIBase()}/${chatId}/agent-settings`)
    return response.data
  }

  /**
   * Update agent settings for a chat
   */
  async function updateChatAgentSettings(chatId: number, data: AgentSettingsUpdateRequest): Promise<AgentSettings> {
    const response = await axios.put(`${getChatsAPIBase()}/${chatId}/agent-settings`, data)
    return response.data
  }

  return {
    getChatAgentSettings,
    updateChatAgentSettings,
  }
}
