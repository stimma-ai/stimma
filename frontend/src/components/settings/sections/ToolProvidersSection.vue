<template>
  <div>
    <div class="flex items-center gap-3 mb-4">
      <h3 class="text-base font-medium text-content">Tool Providers</h3>
      <div class="flex items-center gap-1.5 text-xs text-blue-500 bg-blue-500/10 border border-blue-500/30 rounded-full px-2.5 py-1">
        <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
        <span>Applies to all profiles</span>
      </div>
    </div>
    <p class="text-sm text-content-tertiary mb-6">
      Connect tool providers to expand Stimma's capabilities. Providers can be local processes
      or remote services that implement the Stimma Tools Protocol.
    </p>

    <!-- Stimma Cloud Section -->
    <div class="mb-6">
      <h4 class="text-sm font-medium text-content-secondary mb-3">Stimma Cloud</h4>
      <div class="rounded-lg bg-surface/50 border border-edge overflow-hidden">
        <!-- Not logged in state -->
        <div v-if="!isAuthenticated" class="px-4 py-3">
          <div class="flex items-center gap-3">
            <div class="flex-shrink-0 w-10 h-10 rounded-full bg-gradient-to-br from-teal-600 via-cyan-500 to-indigo-500 flex items-center justify-center">
              <svg class="w-5 h-5 text-content" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z" />
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm text-content-secondary">Stimma Cloud tools</p>
              <p class="text-xs text-content-muted mt-0.5">The newest closed image and video models, plus a hosted agent. Works alongside the providers below.</p>
            </div>
            <button
              @click="handleCloudConnect"
              :disabled="isCloudConnecting"
              class="flex-shrink-0 px-3.5 py-1.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded-lg text-xs font-medium transition-all disabled:opacity-60"
            >
              {{ isCloudConnecting ? 'Connecting...' : 'Connect' }}
            </button>
          </div>
        </div>

        <!-- Logged in state -->
        <template v-else>
          <!-- Card Header -->
          <div class="flex items-center gap-3 px-4 py-3">
            <!-- Status dot -->
            <div
              class="w-2.5 h-2.5 rounded-full flex-shrink-0"
              :class="{
                'bg-green-500': cloudProvider?.status === 'connected',
                'bg-yellow-400': cloudProvider?.status === 'connecting',
                'bg-red-500': cloudProvider?.status === 'error',
                'bg-zinc-500': !cloudProvider || cloudProvider?.status === 'disconnected'
              }"
              :title="cloudProvider?.status || 'disconnected'"
            ></div>

            <!-- Title and subtitle -->
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <h4 class="text-sm font-medium" :class="cloudProvider?.enabled !== false ? 'text-content' : 'text-content-muted'">Stimma Cloud</h4>
                <span v-if="cloudProvider?.enabled === false" class="text-xs text-content-muted">(Disabled)</span>
                <!-- Tier badge -->
                <span
                  v-if="cloudUser?.tier && cloudProvider?.enabled !== false"
                  class="text-[10px] px-1 py-px rounded"
                  :class="hasPaidSubscription ? 'bg-rose-100 text-rose-600 border border-rose-200 dark:bg-rose-500/20 dark:text-rose-400 dark:border-rose-500/30' : 'bg-surface-hover/50 text-content-tertiary border border-edge/30'"
                >
                  {{ getPlanDisplayName(cloudUser) }}
                </span>
                <!-- Connecting indicator -->
                <span
                  v-if="cloudProvider?.status === 'connecting' && cloudProvider?.enabled !== false"
                  class="text-xs text-content-muted"
                >
                  Connecting...
                </span>
              </div>
              <p class="text-xs text-content-tertiary">{{ user?.email }}</p>
            </div>

            <!-- 3-dots menu -->
            <button
              ref="cloudMenuButtonRef"
              @click="toggleCloudMenu"
              class="p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors"
              title="More options"
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path fill-rule="evenodd" d="M10.5 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

          <!-- Error message -->
          <div
            v-if="cloudProvider?.error_message && cloudProvider?.status === 'error'"
            class="px-4 py-2 bg-red-500/10 border-t border-red-500/20"
          >
            <div class="flex items-start gap-2 ml-[22px]">
              <svg class="w-4 h-4 text-red-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              <p class="text-xs text-red-500">{{ cloudProvider?.error_message }}</p>
            </div>
          </div>

          <!-- Card Body - Account info & upgrade prompt -->
          <div class="px-4 pb-4 pt-2 border-t border-edge/50">
            <div class="ml-[22px]">
              <!-- Credits display for paid tiers -->
              <div v-if="hasPaidSubscription" class="flex items-center gap-2 text-sm">
                <span class="text-content-tertiary">Balance:</span>
                <span class="text-content font-medium">{{ formatBalance(cloudUser?.credits) || '$0.00' }}</span>
                <a
                  :href="cloudBaseUrl + '/link/addcredits'"
                  target="_blank"
                  class="text-xs text-blue-500 hover:text-blue-500 hover:underline ml-2"
                >
                  Add balance
                </a>
              </div>

              <!-- Upgrade prompt for free/BYOAI tier -->
              <div v-else class="flex items-center gap-3">
                <p class="text-sm text-content-muted">Subscribe to use Stimma Cloud tools</p>
                <a
                  :href="cloudBaseUrl + '/link/getstarted'"
                  target="_blank"
                  class="text-xs px-2.5 py-1 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded font-medium transition-colors"
                >
                  Get Started
                </a>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Other Providers Section -->
    <h4 class="text-sm font-medium text-content-secondary mb-3">Tool Providers</h4>

    <!-- Provider list -->
    <div class="space-y-4">
      <div
        v-for="provider in otherProviders"
        :key="provider.id"
        class="bg-surface-raised/50 rounded-lg overflow-hidden"
      >
        <!-- Card Header -->
        <div class="flex items-center gap-3 px-4 py-3">
          <!-- Status dot -->
          <div
            class="w-2.5 h-2.5 rounded-full flex-shrink-0"
            :class="{
              'bg-green-500': provider.status === 'connected',
              'bg-yellow-400': provider.status === 'connecting' || provider.status === 'disconnected',
              'bg-red-500': provider.status === 'error',
              'bg-zinc-500': provider.status === 'unknown'
            }"
            :title="provider.status"
          ></div>

          <!-- Title and subtitle -->
          <div class="min-w-0 flex-1">
            <!-- Editable name (for non-builtin providers) -->
            <div v-if="editingNameProvider === provider.id" class="flex items-center gap-2">
              <input
                ref="nameInputRef"
                :value="getEditValue(provider.id, 'name') ?? provider.name"
                @input="setEditValue(provider.id, 'name', $event.target.value)"
                @blur="finishEditingName(provider.id)"
                @keydown.enter="finishEditingName(provider.id)"
                @keydown.escape="cancelEditingName()"
                type="text"
                class="flex-1 min-w-0 bg-surface-raised border border-edge rounded px-2 py-0.5 text-sm font-medium text-content focus:outline-none focus:border-blue-500"
              />
            </div>
            <div v-else class="flex items-center gap-1.5 group">
              <h4 class="text-sm font-medium" :class="provider.enabled ? 'text-content' : 'text-content-muted'">{{ provider.name }}</h4>
              <span v-if="!provider.enabled" class="text-xs text-content-muted">(Disabled)</span>
              <!-- Pencil icon for non-builtin providers -->
              <button
                v-if="provider.type !== 'builtin'"
                @click="startEditingName(provider)"
                class="p-0.5 text-content-muted hover:text-content-secondary opacity-0 group-hover:opacity-100 transition-opacity"
                title="Rename"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                </svg>
              </button>
            </div>
            <p class="text-xs text-content-tertiary">{{ getProviderTypeLabel(provider.type) }}<span v-if="provider.tool_count != null"> · {{ provider.tool_count }} tool{{ provider.tool_count !== 1 ? 's' : '' }}</span></p>
          </div>

          <!-- 3-dots menu -->
          <button
            :ref="el => setMenuButtonRef(provider.id, el)"
            @click="toggleProviderMenu(provider.id)"
            class="p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors"
            title="More options"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
              <path fill-rule="evenodd" d="M10.5 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Zm0 6a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>

        <!-- Error message (shown when status is error or disconnected with an error) -->
        <div
          v-if="provider.error_message && (provider.status === 'error' || provider.status === 'disconnected')"
          class="px-4 py-2 bg-red-500/10 border-t border-red-500/20"
        >
          <div class="flex items-start gap-2 ml-[22px]">
            <svg class="w-4 h-4 text-red-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
            </svg>
            <p class="text-xs text-red-500">{{ provider.error_message }}</p>
          </div>
        </div>

        <!-- Card Body (always visible) -->
        <div class="px-4 pb-4 pt-2 border-t border-edge/50">
          <!-- Indent to align with title (status dot w-2.5 + gap-3 = 22px) -->
          <div class="ml-[22px] space-y-3">
            <!-- Gemini: API Key -->
            <template v-if="provider.type === 'builtin' && provider.id === 'gemini'">
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">API Key</label>
                <div class="flex-1 min-w-0">
                  <input
                    :value="getEditValue(provider.id, 'api_key') ?? provider.api_key ?? '${GEMINI_API_KEY}'"
                    @input="setEditValue(provider.id, 'api_key', $event.target.value)"
                    @blur="saveInlineEdit(provider.id, 'api_key')"
                    type="text"
                    placeholder="${GEMINI_API_KEY}"
                    class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <p class="text-xs text-content-muted mt-1">Use ${GEMINI_API_KEY} to read from environment variable</p>
                </div>
              </div>
            </template>

            <!-- Stdio: Command + Args -->
            <template v-if="provider.type === 'stdio'">
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">Command</label>
                <input
                  :value="getEditValue(provider.id, 'command') ?? provider.command ?? ''"
                  @input="setEditValue(provider.id, 'command', $event.target.value)"
                  @blur="saveInlineEdit(provider.id, 'command')"
                  type="text"
                  placeholder="/path/to/tool"
                  class="flex-1 min-w-0 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">Arguments</label>
                <input
                  :value="getEditValue(provider.id, 'args') ?? serializeArgs(provider.args) ?? ''"
                  @input="setEditValue(provider.id, 'args', $event.target.value)"
                  @blur="saveInlineEdit(provider.id, 'args')"
                  type="text"
                  placeholder="--port 8080 --config &quot;my config.json&quot;"
                  class="flex-1 min-w-0 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">Working Dir</label>
                <input
                  :value="getEditValue(provider.id, 'working_dir') ?? provider.working_dir ?? ''"
                  @input="setEditValue(provider.id, 'working_dir', $event.target.value)"
                  @blur="saveInlineEdit(provider.id, 'working_dir')"
                  type="text"
                  placeholder="/path/to/working/directory (optional)"
                  class="flex-1 min-w-0 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
            </template>

            <!-- WebSocket: URL + Token -->
            <template v-if="provider.type === 'websocket'">
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">URL</label>
                <input
                  :value="getEditValue(provider.id, 'url') ?? provider.url ?? ''"
                  @input="setEditValue(provider.id, 'url', $event.target.value)"
                  @blur="saveInlineEdit(provider.id, 'url')"
                  type="text"
                  placeholder="ws://localhost:8080"
                  class="flex-1 min-w-0 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                />
              </div>
              <div class="flex items-start gap-3">
                <label class="text-xs text-content-tertiary w-20 pt-1.5 shrink-0">Token</label>
                <div class="flex-1 min-w-0">
                  <input
                    :value="getEditValue(provider.id, 'auth_token') ?? provider.auth_token ?? ''"
                    @input="setEditValue(provider.id, 'auth_token', $event.target.value)"
                    @blur="saveInlineEdit(provider.id, 'auth_token')"
                    type="text"
                    placeholder="Bearer token (optional)"
                    class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <p class="text-xs text-content-muted mt-1">Sent as Authorization: Bearer &lt;token&gt;</p>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="providers.length === 0" class="text-center py-8 text-content-tertiary">
      No tool providers configured
    </div>

    <!-- Add tool button -->
    <div class="mt-4">
      <button
        @click="openAddModal"
        class="flex items-center gap-2 px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        Add Provider
      </button>
    </div>

    <!-- Add modal -->
    <Teleport to="body">
      <div
        v-if="showModal"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closeModal"
        @keydown.escape.stop="closeModal"
        tabindex="-1"
        ref="addModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg p-6 w-[480px] max-w-[90vw]">
          <h3 class="text-lg font-medium text-content mb-4">Add Tool Provider</h3>

          <!-- Tool type selection -->
          <div class="mb-4">
            <label class="block text-xs text-content-tertiary mb-2">Provider Type</label>
            <div class="flex gap-4">
              <label class="flex items-center gap-2 text-sm text-content-secondary cursor-pointer">
                <input
                  type="radio"
                  v-model="formData.type"
                  value="websocket"
                  class="text-blue-500 focus:ring-blue-500"
                />
                WebSocket connection
              </label>
              <label class="flex items-center gap-2 text-sm text-content-secondary cursor-pointer">
                <input
                  type="radio"
                  v-model="formData.type"
                  value="stdio"
                  class="text-blue-500 focus:ring-blue-500"
                />
                Local Process
              </label>
            </div>
          </div>

          <!-- Name field -->
          <div class="mb-4">
            <label class="block text-xs text-content-tertiary mb-1">Name</label>
            <input
              v-model="formData.name"
              type="text"
              placeholder="My Tool Provider"
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
            />
            <p v-if="nameError" class="text-xs text-red-500 mt-1">{{ nameError }}</p>
          </div>

          <!-- Stdio-specific fields -->
          <div v-if="formData.type === 'stdio'" class="space-y-4 mb-4">
            <div>
              <label class="block text-xs text-content-tertiary mb-1">Command</label>
              <input
                v-model="formData.command"
                type="text"
                placeholder="/path/to/tool"
                class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
              />
              <p class="text-xs text-content-muted mt-1">Path to the executable that implements Stimma Tools Protocol</p>
            </div>
            <div>
              <label class="block text-xs text-content-tertiary mb-1">Arguments (optional)</label>
              <input
                v-model="formData.args"
                type="text"
                placeholder="--port 8080 --config &quot;my config.json&quot;"
                class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono text-xs"
              />
              <p class="text-xs text-content-muted mt-1">Command line arguments (shell-style quoting supported)</p>
            </div>
            <div>
              <label class="block text-xs text-content-tertiary mb-1">Working Directory (optional)</label>
              <input
                v-model="formData.working_dir"
                type="text"
                placeholder="/path/to/working/directory"
                class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono text-xs"
              />
              <p class="text-xs text-content-muted mt-1">Directory to run the process in (defaults to current directory)</p>
            </div>
          </div>

          <!-- WebSocket-specific fields -->
          <div v-if="formData.type === 'websocket'" class="space-y-4 mb-4">
            <div>
              <label class="block text-xs text-content-tertiary mb-1">WebSocket URL</label>
              <input
                v-model="formData.url"
                type="text"
                placeholder="ws://localhost:8080"
                class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
              />
              <p class="text-xs text-content-muted mt-1">WebSocket endpoint for Stimma Tools Protocol</p>
            </div>
            <div>
              <label class="block text-xs text-content-tertiary mb-1">Token (optional)</label>
              <input
                v-model="formData.auth_token"
                type="text"
                placeholder="Bearer token"
                class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500 font-mono"
              />
              <p class="text-xs text-content-muted mt-1">Sent as Authorization: Bearer &lt;token&gt;</p>
            </div>
          </div>

          <!-- Test connection result -->
          <div v-if="testResult" class="mb-4 p-3 rounded-lg" :class="testResult.success ? 'bg-green-500/15 border border-green-500/30' : 'bg-red-500/15 border border-red-500/30'">
            <div v-if="testResult.success" class="flex items-start gap-2">
              <svg class="w-5 h-5 text-green-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <div>
                <p class="text-sm font-medium text-green-500">Connection successful</p>
                <p class="text-xs text-content-tertiary mt-1">
                  {{ testResult.provider_name }}
                  <span v-if="testResult.provider_version" class="text-content-muted">v{{ testResult.provider_version }}</span>
                  <span v-if="testResult.tool_count !== null"> · {{ testResult.tool_count }} tool{{ testResult.tool_count !== 1 ? 's' : '' }}</span>
                </p>
              </div>
            </div>
            <div v-else class="flex items-start gap-2">
              <svg class="w-5 h-5 text-red-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <div>
                <p class="text-sm font-medium text-red-500">Connection failed</p>
                <p class="text-xs text-content-tertiary mt-1">{{ testResult.error }}</p>
              </div>
            </div>
          </div>

          <!-- Form actions -->
          <div class="flex justify-between gap-3">
            <button
              @click="testConnection"
              :disabled="!canTest || testing"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover disabled:opacity-50 disabled:cursor-not-allowed text-content rounded-lg font-medium transition-colors"
            >
              {{ testing ? 'Testing...' : 'Test Connection' }}
            </button>
            <div class="flex gap-3">
              <button
                @click="closeModal"
                class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                @click="saveProvider"
                :disabled="!canSave || saving"
                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
              >
                {{ saving ? 'Adding...' : 'Add Provider' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete confirmation modal -->
    <Teleport to="body">
      <div
        v-if="deleteConfirm"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="deleteConfirm = null"
        @keydown.escape.stop="deleteConfirm = null"
        tabindex="-1"
        ref="deleteModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg p-6 max-w-sm">
          <h3 class="text-lg font-medium text-content mb-2">Remove Tool Provider</h3>
          <p class="text-sm text-content-tertiary mb-4">
            Are you sure you want to remove <strong class="text-content">{{ deleteConfirm.name }}</strong>?
          </p>
          <div class="flex justify-end gap-3">
            <button
              @click="deleteConfirm = null"
              class="px-4 py-2 bg-surface-raised hover:bg-surface-hover text-content rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              @click="deleteTool"
              :disabled="saving"
              class="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg font-medium transition-colors"
            >
              {{ saving ? 'Removing...' : 'Remove' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Logs modal -->
    <Teleport to="body">
      <div
        v-if="logsModal.provider"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closeLogsModal"
        @keydown.escape.stop="closeLogsModal"
        tabindex="-1"
        ref="logsModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg w-[700px] max-w-[90vw] max-h-[80vh] flex flex-col">
          <!-- Header -->
          <div class="flex items-center justify-between px-4 py-3 border-b border-edge">
            <div>
              <h3 class="text-lg font-medium text-content">Process Logs</h3>
              <p class="text-xs text-content-tertiary">{{ logsModal.provider?.name }}</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                @click="refreshLogs"
                :disabled="logsModal.loading"
                class="px-3 py-1.5 bg-surface-raised hover:bg-surface-hover disabled:opacity-50 text-content rounded font-medium text-sm transition-colors flex items-center gap-1.5"
              >
                <svg class="w-4 h-4" :class="{ 'animate-spin': logsModal.loading }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
                Refresh
              </button>
              <button
                @click="clearLogsDisplay"
                class="px-3 py-1.5 bg-surface-raised hover:bg-surface-hover text-content rounded font-medium text-sm transition-colors"
              >
                Clear
              </button>
              <button
                @click="closeLogsModal"
                class="p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors"
              >
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Log content -->
          <div class="flex-1 overflow-auto p-4 min-h-[300px]" ref="logsContentRef">
            <div v-if="logsModal.loading && logsModal.lines.length === 0" class="text-center text-content-tertiary py-8">
              Loading logs...
            </div>
            <div v-else-if="logsModal.lines.length === 0" class="text-center text-content-tertiary py-8">
              No logs available
            </div>
            <pre v-else class="text-xs font-mono text-content-secondary whitespace-pre-wrap break-words">{{ logsModal.lines.join('\n') }}</pre>
          </div>

          <!-- Footer -->
          <div class="px-4 py-2 border-t border-edge text-xs text-content-muted">
            Showing {{ logsModal.lines.length }} of {{ logsModal.totalLines }} lines
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Tools modal -->
    <Teleport to="body">
      <div
        v-if="toolsModal.provider"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop backdrop-blur-sm"
        @click.self="closeToolsModal"
        @keydown.escape.stop="closeToolsModal"
        tabindex="-1"
        ref="toolsModalRef"
      >
        <div class="bg-surface border border-edge rounded-lg w-[600px] max-w-[90vw] max-h-[80vh] flex flex-col">
          <!-- Header -->
          <div class="flex items-center justify-between px-4 py-3 border-b border-edge">
            <div class="flex items-center gap-2">
              <div>
                <h3 class="text-lg font-medium text-content">Available Tools</h3>
                <p class="text-xs text-content-tertiary">{{ toolsModal.provider?.name }}</p>
                <!-- Dev mode: Provider registration info -->
                <div v-if="devModeRef && toolsModal.provider" class="mt-1 text-xs font-mono text-content-muted bg-overlay-subtle rounded px-2 py-1">
                  <span class="text-blue-500">max_concurrent:</span> {{ toolsModal.provider.max_concurrent ?? 'N/A' }}
                  <span v-if="toolsModal.provider.queue_status" class="ml-2">
                    <span class="text-content-muted">|</span>
                    <span class="text-green-500 ml-2">running:</span> {{ toolsModal.provider.queue_status.running ?? 0 }}
                    <span class="text-yellow-400 ml-2">queued:</span> {{ toolsModal.provider.queue_status.queued ?? 0 }}
                    <span class="text-content-tertiary ml-2">capacity:</span> {{ toolsModal.provider.queue_status.capacity ?? 0 }}
                  </span>
                </div>
              </div>
              <!-- Copy all tools button (dev mode only) -->
              <button
                v-if="devModeRef"
                @click="copyAllToolsJson"
                :disabled="toolsModal.loading || toolsModal.tools.length === 0"
                class="p-1.5 text-content-muted hover:text-content-secondary hover:bg-surface-hover disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                :title="copiedAllTools ? 'Copied!' : 'Copy all tools as JSON'"
              >
                <svg v-if="copiedAllTools" class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                <svg v-else class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>
            <button
              @click="closeToolsModal"
              class="p-1.5 text-content-tertiary hover:text-content hover:bg-surface-hover rounded transition-colors"
            >
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Search filter -->
          <div class="px-4 py-2 border-b border-edge">
            <input
              v-model="toolsFilter"
              type="text"
              placeholder="Filter tools..."
              class="w-full bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content placeholder-content-muted focus:outline-none focus:border-blue-500"
            />
          </div>

          <!-- Tools list -->
          <div class="flex-1 overflow-auto min-h-[200px]">
            <div v-if="toolsModal.loading" class="text-center text-content-tertiary py-8">
              Loading tools...
            </div>
            <div v-else-if="toolsModal.tools.length === 0" class="text-center text-content-tertiary py-8">
              No tools available
            </div>
            <div v-else-if="filteredTools.length === 0" class="text-center text-content-tertiary py-8">
              No tools match "{{ toolsFilter }}"
            </div>
            <div v-else class="divide-y divide-edge/50">
              <div
                v-for="tool in filteredTools"
                :key="tool.full_tool_id"
                class="px-4 py-3 hover:bg-surface-raised/30"
              >
                <div class="flex items-start gap-3">
                  <div class="flex-1 min-w-0">
                    <h4 class="text-sm font-medium text-content">{{ tool.name }}</h4>
                    <p v-if="tool.metadata?.description" class="text-xs text-content-tertiary mt-0.5 line-clamp-2">
                      {{ tool.metadata.description }}
                    </p>
                    <div class="flex items-center gap-2 mt-1 flex-wrap">
                      <span
                        v-for="tt in (tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : []))"
                        :key="tt"
                        class="text-xs text-content-muted bg-surface-raised/50 rounded px-1.5 py-0.5"
                      >
                        {{ formatTaskTypeLabel(tt) }}
                      </span>
                      <span class="text-xs text-content-muted font-mono">{{ tool.tool_id }}</span>
                    </div>
                  </div>
                  <!-- Copy JSON button (dev mode only) -->
                  <button
                    v-if="devModeRef"
                    @click="copyToolJson(tool.full_tool_id)"
                    class="p-1.5 text-content-muted hover:text-content-secondary hover:bg-surface-hover rounded transition-colors shrink-0"
                    :title="copiedToolId === tool.full_tool_id ? 'Copied!' : 'Copy raw JSON'"
                  >
                    <svg v-if="copiedToolId === tool.full_tool_id" class="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-4 py-2 border-t border-edge text-xs text-content-muted">
            <template v-if="toolsFilter && filteredTools.length !== toolsModal.tools.length">
              {{ filteredTools.length }} of {{ toolsModal.tools.length }} tools
            </template>
            <template v-else>
              {{ toolsModal.tools.length }} tool{{ toolsModal.tools.length !== 1 ? 's' : '' }}
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Cloud menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="showCloudMenu && cloudMenuPosition"
        data-cloud-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-[10010]"
        :style="{ top: cloudMenuPosition.top + 'px', left: cloudMenuPosition.left + 'px' }"
      >
        <button
          @click="toggleCloudEnabled(); closeCloudMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg v-if="cloudProvider?.enabled !== false" class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
          </svg>
          <svg v-else class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {{ cloudProvider?.enabled !== false ? 'Disable Tools' : 'Enable Tools' }}
        </button>
        <button
          v-if="cloudProvider?.tool_count > 0"
          @click="openCloudToolsModal(); closeCloudMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
          </svg>
          View Tools ({{ cloudProvider.tool_count }})
        </button>
        <button
          @click="openCloudLogsModal(); closeCloudMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
          </svg>
          View Logs
        </button>
      </div>
    </Teleport>

    <!-- Provider menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="openMenuProvider && menuPosition"
        data-provider-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-[10010]"
        :style="{ top: menuPosition.top + 'px', left: menuPosition.left + 'px' }"
      >
        <button
          @click="toggleEnabledFromMenu(openMenuProvider)"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg v-if="getProviderById(openMenuProvider)?.enabled" class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
          </svg>
          <svg v-else class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {{ getProviderById(openMenuProvider)?.enabled ? 'Disable' : 'Enable' }}
        </button>
        <button
          v-if="getProviderById(openMenuProvider)?.tool_count > 0"
          @click="openToolsModal(getProviderById(openMenuProvider)); closeProviderMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
          </svg>
          View Tools ({{ getProviderById(openMenuProvider).tool_count }})
        </button>
        <button
          v-if="getProviderById(openMenuProvider)?.type === 'stdio' || getProviderById(openMenuProvider)?.type === 'websocket'"
          @click="openLogsModal(getProviderById(openMenuProvider)); closeProviderMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-content hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
          </svg>
          View Logs
        </button>
        <button
          v-if="getProviderById(openMenuProvider)?.type !== 'builtin'"
          @click="confirmDelete(getProviderById(openMenuProvider)); closeProviderMenu()"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-surface-hover transition-colors text-left"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
          </svg>
          Remove
        </button>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useAuth } from '../../../composables/useAuth'
import { useCloudAccount, formatBalance, getPlanDisplayName } from '../../../composables/useCloudAccount'
import { copyToClipboard } from '../../../utils/clipboard'
import { addToast } from '../../../composables/useToasts'
import { devModeRef } from '../../../appConfig'
import { formatTaskTypeLabel } from '../../../utils/taskTypeIcons'

const props = defineProps({
  providers: {
    type: Array,
    default: () => []
  }
})

// Auth and cloud account state
const { user, isAuthenticated, signInWithBrowser } = useAuth()
const { cloudBaseUrl, cloudUser, fetchCloudAccount, ensureCloudBaseUrl } = useCloudAccount()

// Signed-out Connect button on the Stimma Cloud card
const isCloudConnecting = ref(false)

async function handleCloudConnect() {
  isCloudConnecting.value = true
  try {
    await signInWithBrowser()
  } catch (error) {
    addToast(error.message || 'Connection failed', 'error')
  } finally {
    isCloudConnecting.value = false
  }
}

// Cloud dashboard URL
const cloudDashboardUrl = computed(() => cloudBaseUrl.value + '/link/dashboard')

// Check if user has a paid subscription (not free tier or BYOAI)
const hasPaidSubscription = computed(() => {
  if (!cloudUser.value) return false
  const tier = (cloudUser.value.tier || '').toLowerCase()
  return tier && tier !== 'free' && tier !== 'byoai'
})

// Cloud provider from the providers list
const cloudProvider = computed(() => {
  return props.providers.find(p => p.id === 'stimma-cloud')
})

// Tool providers (excluding stimma-cloud which has its own section)
const otherProviders = computed(() => {
  return props.providers.filter(p => p.id !== 'stimma-cloud')
})

// Init cloud account info
async function initCloudAccount() {
  // Ensure cloud base URL is loaded
  await ensureCloudBaseUrl()
  // Fetch cloud account if authenticated
  if (isAuthenticated.value) {
    await fetchCloudAccount()
  }
}

// Open cloud tools modal (reuses existing tools modal)
function openCloudToolsModal() {
  const provider = cloudProvider.value
  if (provider) {
    openToolsModal(provider)
  }
}

const emit = defineEmits(['update', 'create', 'delete'])

const saving = ref(false)
const togglingProvider = ref(null)
const showModal = ref(false)
const deleteConfirm = ref(null)
const testing = ref(false)
const testResult = ref(null)
const addModalRef = ref(null)
const deleteModalRef = ref(null)
const logsModalRef = ref(null)
const logsContentRef = ref(null)
const toolsModalRef = ref(null)
const nameInputRef = ref(null)

// Logs modal state
const logsModal = ref({
  provider: null,
  lines: [],
  totalLines: 0,
  loading: false,
})
const logsRefreshInterval = ref(null)

// Tools modal state
const toolsModal = ref({
  provider: null,
  tools: [],
  loading: false,
})

// Copy JSON state
const copiedToolId = ref(null)
const copiedAllTools = ref(false)

// Tools filter
const toolsFilter = ref('')

const filteredTools = computed(() => {
  const query = toolsFilter.value.toLowerCase().trim()
  if (!query) return toolsModal.value.tools
  return toolsModal.value.tools.filter(tool =>
    tool.name.toLowerCase().includes(query) ||
    tool.tool_id.toLowerCase().includes(query) ||
    (tool.task_types || []).some(tt => tt.toLowerCase().includes(query))
  )
})

// Name editing state
const editingNameProvider = ref(null)

// Provider menu state
const openMenuProvider = ref(null)
const menuPosition = ref(null)
const menuButtonRefs = ref({})

// Cloud menu state
const showCloudMenu = ref(false)
const cloudMenuPosition = ref(null)
const cloudMenuButtonRef = ref(null)

function toggleCloudMenu() {
  if (showCloudMenu.value) {
    closeCloudMenu()
  } else {
    const button = cloudMenuButtonRef.value
    if (button) {
      const rect = button.getBoundingClientRect()
      cloudMenuPosition.value = {
        top: rect.bottom + 4,
        left: rect.right - 140
      }
    }
    showCloudMenu.value = true
  }
}

function closeCloudMenu() {
  showCloudMenu.value = false
  cloudMenuPosition.value = null
}

function openCloudLogsModal() {
  // Use cloudProvider if available, otherwise create a minimal object for logs
  const provider = cloudProvider.value || { id: 'stimma-cloud', name: 'Stimma Cloud' }
  openLogsModal(provider)
}

function setMenuButtonRef(providerId, el) {
  if (el) {
    menuButtonRefs.value[providerId] = el
  } else {
    delete menuButtonRefs.value[providerId]
  }
}

function getProviderById(providerId) {
  return props.providers.find(p => p.id === providerId)
}

// Focus modals when opened so they can capture Escape key
watch(showModal, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    addModalRef.value?.focus()
  }
})

watch(deleteConfirm, async (confirm) => {
  if (confirm) {
    await nextTick()
    deleteModalRef.value?.focus()
  }
})

watch(() => logsModal.value.provider, async (provider) => {
  if (provider) {
    await nextTick()
    logsModalRef.value?.focus()
  }
})

watch(() => toolsModal.value.provider, async (provider) => {
  if (provider) {
    await nextTick()
    toolsModalRef.value?.focus()
  }
})

// Close menus when clicking outside
function handleClickOutside(event) {
  if (openMenuProvider.value) {
    // Check if click is outside the menu button and dropdown
    const menuButton = event.target.closest('[title="More options"]')
    const menuDropdown = event.target.closest('[data-provider-menu]')
    if (!menuButton && !menuDropdown) {
      closeProviderMenu()
    }
  }
  if (showCloudMenu.value) {
    const cloudMenuButton = event.target.closest('[title="More options"]')
    const cloudMenuDropdown = event.target.closest('[data-cloud-menu]')
    if (!cloudMenuButton && !cloudMenuDropdown) {
      closeCloudMenu()
    }
  }
}

function handleEscapeKey(event) {
  if (event.key === 'Escape') {
    if (openMenuProvider.value) {
      closeProviderMenu()
    }
    if (showCloudMenu.value) {
      closeCloudMenu()
    }
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleEscapeKey)
  // Initialize cloud account info
  initCloudAccount()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleEscapeKey)
  // Clear logs auto-refresh if active
  if (logsRefreshInterval.value) {
    clearInterval(logsRefreshInterval.value)
    logsRefreshInterval.value = null
  }
})

// Inline editing state - tracks pending edits per provider per field
const inlineEdits = ref({})

const formData = ref({
  type: 'websocket',
  name: '',
  command: '',
  args: '',
  working_dir: '',
  url: '',
  auth_token: '',
})

/**
 * Convert a name to a URL-safe slug ID
 */
function nameToSlug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

/**
 * Check if a name is unique among existing providers
 */
function isNameUnique(name) {
  const normalizedName = name.trim().toLowerCase()
  return !props.providers.some(p => p.name.toLowerCase() === normalizedName)
}

const nameError = computed(() => {
  if (!formData.value.name.trim()) return null
  if (!isNameUnique(formData.value.name)) return 'A provider with this name already exists'
  return null
})

const canSave = computed(() => {
  if (!formData.value.name.trim()) return false
  if (nameError.value) return false
  if (formData.value.type === 'stdio' && !formData.value.command) return false
  if (formData.value.type === 'websocket' && !formData.value.url) return false
  return true
})

const canTest = computed(() => {
  if (formData.value.type === 'stdio' && !formData.value.command) return false
  if (formData.value.type === 'websocket' && !formData.value.url) return false
  return true
})

async function testConnection() {
  if (!canTest.value || testing.value) return

  testing.value = true
  testResult.value = null

  try {
    const body = {
      type: formData.value.type,
    }

    if (formData.value.type === 'stdio') {
      body.command = formData.value.command
      const parsedArgs = parseArgs(formData.value.args)
      if (parsedArgs.length > 0) {
        body.args = parsedArgs
      }
      if (formData.value.working_dir) {
        body.working_dir = formData.value.working_dir
      }
    } else {
      body.url = formData.value.url
      if (formData.value.auth_token) {
        body.auth_token = formData.value.auth_token
      }
    }

    const response = await fetch('/api/tools/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    testResult.value = await response.json()
  } catch (err) {
    testResult.value = {
      success: false,
      error: `Network error: ${err.message}`,
      error_type: 'network',
    }
  } finally {
    testing.value = false
  }
}

// Name editing functions
async function startEditingName(provider) {
  editingNameProvider.value = provider.id
  // Initialize the edit value with current name
  setEditValue(provider.id, 'name', provider.name)
  await nextTick()
  // Focus and select the input
  if (nameInputRef.value) {
    nameInputRef.value.focus()
    nameInputRef.value.select()
  }
}

function finishEditingName(providerId) {
  const newName = getEditValue(providerId, 'name')?.trim()
  if (newName && newName !== props.providers.find(p => p.id === providerId)?.name) {
    // Save the name change
    emit('update', { providerId, data: { name: newName } })
  }
  // Clear edit state
  if (inlineEdits.value[providerId]) {
    delete inlineEdits.value[providerId]['name']
  }
  editingNameProvider.value = null
}

function cancelEditingName() {
  if (editingNameProvider.value) {
    // Clear edit state without saving
    if (inlineEdits.value[editingNameProvider.value]) {
      delete inlineEdits.value[editingNameProvider.value]['name']
    }
    editingNameProvider.value = null
  }
}

// Inline editing helpers
function getEditValue(providerId, field) {
  return inlineEdits.value[providerId]?.[field]
}

function setEditValue(providerId, field, value) {
  if (!inlineEdits.value[providerId]) {
    inlineEdits.value[providerId] = {}
  }
  inlineEdits.value[providerId][field] = value
}

function saveInlineEdit(providerId, field) {
  const value = getEditValue(providerId, field)
  if (value === undefined) return // No edit was made

  const provider = props.providers.find(p => p.id === providerId)
  if (!provider) return

  // Get the original value to compare
  let originalValue
  if (field === 'args') {
    originalValue = serializeArgs(provider.args) ?? ''
  } else if (field === 'api_key') {
    originalValue = provider.api_key ?? '${GEMINI_API_KEY}'
  } else {
    originalValue = provider[field] ?? ''
  }

  // Only save if the value actually changed
  if (value === originalValue) {
    // Clear the edit state
    if (inlineEdits.value[providerId]) {
      delete inlineEdits.value[providerId][field]
    }
    return
  }

  // Build the update data
  const data = {}
  if (field === 'args') {
    data.args = parseArgs(value)
  } else {
    data[field] = value
  }

  emit('update', { providerId, data })

  // Clear the edit state
  if (inlineEdits.value[providerId]) {
    delete inlineEdits.value[providerId][field]
  }
}

function getProviderTypeLabel(type) {
  switch (type) {
    case 'builtin': return 'Built-in tool provider'
    case 'stdio': return 'Stimma Tools Protocol · Local Process'
    case 'websocket': return 'Stimma Tools Protocol · WebSocket'
    default: return type
  }
}

/**
 * Parse a shell-style argument string into an array.
 * Supports single quotes, double quotes, and backslash escaping.
 */
function parseArgs(argsString) {
  if (!argsString || !argsString.trim()) return []

  const args = []
  let current = ''
  let inSingleQuote = false
  let inDoubleQuote = false
  let escapeNext = false

  for (let i = 0; i < argsString.length; i++) {
    const char = argsString[i]

    if (escapeNext) {
      current += char
      escapeNext = false
      continue
    }

    if (char === '\\' && !inSingleQuote) {
      escapeNext = true
      continue
    }

    if (char === "'" && !inDoubleQuote) {
      inSingleQuote = !inSingleQuote
      continue
    }

    if (char === '"' && !inSingleQuote) {
      inDoubleQuote = !inDoubleQuote
      continue
    }

    if (char === ' ' && !inSingleQuote && !inDoubleQuote) {
      if (current) {
        args.push(current)
        current = ''
      }
      continue
    }

    current += char
  }

  if (current) {
    args.push(current)
  }

  return args
}

/**
 * Serialize an args array back to a shell-style string.
 * Quotes arguments that contain spaces.
 */
function serializeArgs(argsArray) {
  if (!argsArray || argsArray.length === 0) return ''

  return argsArray.map(arg => {
    if (arg.includes(' ') || arg.includes('"') || arg.includes("'")) {
      // Use double quotes and escape any double quotes inside
      return `"${arg.replace(/"/g, '\\"')}"`
    }
    return arg
  }).join(' ')
}

function toggleProviderMenu(providerId) {
  if (openMenuProvider.value === providerId) {
    openMenuProvider.value = null
    menuPosition.value = null
  } else {
    const button = menuButtonRefs.value[providerId]
    if (button) {
      const rect = button.getBoundingClientRect()
      menuPosition.value = {
        top: rect.bottom + 4,
        left: rect.right - 140 // Align right edge of menu with button
      }
    }
    openMenuProvider.value = providerId
  }
}

function closeProviderMenu() {
  openMenuProvider.value = null
  menuPosition.value = null
}

function toggleEnabledFromMenu(providerId) {
  const provider = getProviderById(providerId)
  if (provider) {
    toggleEnabled(providerId, !provider.enabled)
  }
  closeProviderMenu()
}

function toggleCloudEnabled() {
  const provider = cloudProvider.value
  // enabled defaults to true if not explicitly set
  const currentEnabled = provider?.enabled !== false
  emit('update', { providerId: 'stimma-cloud', data: { enabled: !currentEnabled } })
}

async function toggleEnabled(providerId, enabled) {
  // Prevent multiple clicks
  if (togglingProvider.value) return
  togglingProvider.value = providerId

  try {
    emit('update', { providerId, data: { enabled } })
  } finally {
    // Clear after a short delay to allow the UI to update
    setTimeout(() => {
      togglingProvider.value = null
    }, 500)
  }
}

function openAddModal() {
  formData.value = {
    type: 'websocket',
    name: '',
    command: '',
    args: '',
    working_dir: '',
    url: '',
    auth_token: '',
  }
  testResult.value = null
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

// Logs modal functions
async function openLogsModal(provider) {
  logsModal.value = {
    provider,
    lines: [],
    totalLines: 0,
    loading: true,
  }
  await fetchLogs()
  // Auto-scroll to bottom
  await nextTick()
  if (logsContentRef.value) {
    logsContentRef.value.scrollTop = logsContentRef.value.scrollHeight
  }
  // Start auto-refresh every 1 second
  logsRefreshInterval.value = setInterval(async () => {
    // Check if user is at bottom before fetching
    const container = logsContentRef.value
    const wasAtBottom = container && (container.scrollHeight - container.scrollTop - container.clientHeight < 50)

    await fetchLogs()

    // Only auto-scroll if user was already at bottom
    if (wasAtBottom) {
      await nextTick()
      if (logsContentRef.value) {
        logsContentRef.value.scrollTop = logsContentRef.value.scrollHeight
      }
    }
  }, 1000)
}

function closeLogsModal() {
  // Stop auto-refresh
  if (logsRefreshInterval.value) {
    clearInterval(logsRefreshInterval.value)
    logsRefreshInterval.value = null
  }
  logsModal.value = {
    provider: null,
    lines: [],
    totalLines: 0,
    loading: false,
  }
}

async function fetchLogs() {
  if (!logsModal.value.provider) return

  try {
    const response = await fetch(`/api/tools/providers/${logsModal.value.provider.id}/logs`)
    if (response.ok) {
      const data = await response.json()
      logsModal.value.lines = data.lines || []
      logsModal.value.totalLines = data.total_lines || 0
    }
  } catch (err) {
    console.error('Failed to fetch logs:', err)
  } finally {
    logsModal.value.loading = false
  }
}

async function refreshLogs() {
  logsModal.value.loading = true
  await fetchLogs()
  // Auto-scroll to bottom
  await nextTick()
  if (logsContentRef.value) {
    logsContentRef.value.scrollTop = logsContentRef.value.scrollHeight
  }
}

function clearLogsDisplay() {
  logsModal.value.lines = []
}

// Tools modal functions
async function openToolsModal(provider) {
  toolsModal.value = {
    provider,
    tools: [],
    loading: true,
  }
  await fetchTools()
}

function closeToolsModal() {
  toolsModal.value = {
    provider: null,
    tools: [],
    loading: false,
  }
  toolsFilter.value = ''
  copiedAllTools.value = false
}

async function fetchTools() {
  if (!toolsModal.value.provider) return

  try {
    const response = await fetch(`/api/tools/providers/tools?provider_id=${encodeURIComponent(toolsModal.value.provider.id)}`)
    if (response.ok) {
      const data = await response.json()
      // Sort tools by name
      toolsModal.value.tools = (data || []).sort((a, b) => a.name.localeCompare(b.name))
    }
  } catch (err) {
    console.error('Failed to fetch tools:', err)
  } finally {
    toolsModal.value.loading = false
  }
}

async function copyToolJson(fullToolId) {
  try {
    const response = await fetch(`/api/tools/provider-tool/${fullToolId}/raw-schema`)
    if (!response.ok) {
      throw new Error('Failed to fetch tool schema')
    }
    const data = await response.json()
    const jsonStr = JSON.stringify(data, null, 2)
    const success = await copyToClipboard(jsonStr)

    if (success) {
      copiedToolId.value = fullToolId
      setTimeout(() => {
        copiedToolId.value = null
      }, 2000)
      addToast('Tool JSON copied to clipboard', 'success', 2000)
    }
  } catch (err) {
    console.error('Failed to copy tool JSON:', err)
    addToast('Failed to copy tool JSON', 'error', 3000)
  }
}

async function copyAllToolsJson() {
  try {
    // Fetch raw schema for each tool
    const schemas = await Promise.all(
      toolsModal.value.tools.map(async (tool) => {
        const response = await fetch(`/api/tools/provider-tool/${tool.full_tool_id}/raw-schema`)
        if (!response.ok) return null
        return response.json()
      })
    )

    // Filter out any failed fetches
    const validSchemas = schemas.filter(s => s !== null)
    const jsonStr = JSON.stringify(validSchemas, null, 2)
    const success = await copyToClipboard(jsonStr)

    if (success) {
      copiedAllTools.value = true
      setTimeout(() => {
        copiedAllTools.value = false
      }, 2000)
      addToast(`${validSchemas.length} tool${validSchemas.length !== 1 ? 's' : ''} JSON copied to clipboard`, 'success', 2000)
    }
  } catch (err) {
    console.error('Failed to copy all tools JSON:', err)
    addToast('Failed to copy tools JSON', 'error', 3000)
  }
}

async function saveProvider() {
  saving.value = true
  try {
    const name = formData.value.name.trim()
    const config = {
      id: nameToSlug(name),
      name: name,
      type: formData.value.type,
    }

    if (formData.value.type === 'stdio') {
      config.command = formData.value.command
      const parsedArgs = parseArgs(formData.value.args)
      if (parsedArgs.length > 0) {
        config.args = parsedArgs
      }
      if (formData.value.working_dir) {
        config.working_dir = formData.value.working_dir
      }
    } else {
      config.url = formData.value.url
      if (formData.value.auth_token) {
        config.auth_token = formData.value.auth_token
      }
    }

    emit('create', config)
    closeModal()
  } finally {
    saving.value = false
  }
}

function confirmDelete(provider) {
  deleteConfirm.value = provider
}

async function deleteTool() {
  if (!deleteConfirm.value) return

  saving.value = true
  try {
    emit('delete', deleteConfirm.value.id)
    deleteConfirm.value = null
  } finally {
    saving.value = false
  }
}
</script>
