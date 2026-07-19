<template>
  <div>
    <template v-if="!showModal && !selectedProvider">
    <div v-if="!wizard" class="mb-4 flex items-center gap-3">
      <h3 class="text-xs font-semibold text-content-secondary">Generation Tools</h3>
    </div>

    <p v-if="!wizard" class="mb-6 max-w-2xl text-sm leading-6 text-content-tertiary">
      Generation tools create and edit images, video, and audio.
    </p>

    <div
      v-if="setupRequired && !wizard"
      class="mb-6 flex w-full items-center gap-3 border-b border-edge-subtle px-1 py-2"
    >
      <span class="h-2 w-2 shrink-0 rounded-full bg-amber-400"></span>
      <p class="text-[13px] text-content-secondary">Connect generation tools to generate media.</p>
    </div>

    <div class="divide-y divide-edge-subtle">
      <button
        type="button"
        class="group flex w-full items-center gap-4 px-1 py-4 text-left hover:bg-overlay-subtle"
        @click="!isAuthenticated ? handleCloudConnect() : cloudConnectedWithoutCredits ? openAddCredits() : openProviderDetails('stimma-cloud')"
      >
        <ToolProviderBrandIcon kind="stimma" />
        <div class="min-w-0 flex-1">
          <div class="text-[13px] text-content">{{ STIMMA_TOOL_PROVIDER_DISPLAY_NAME }}</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">
            {{ stimmaProviderDescription }}
          </div>
        </div>
        <template v-if="isAuthenticated">
          <div class="flex min-w-20 shrink-0 items-center justify-end gap-1.5 text-right text-xs" :class="cloudRowStatusClass">
            <Spinner v-if="isProviderConnecting(cloudProvider)" size="sm" />
            <ExclamationCircleIcon v-else-if="isProviderConnectionError(cloudProvider)" class="h-4 w-4" />
            <span v-else-if="cloudRowStatusDot" class="h-2 w-2 shrink-0 rounded-full" :class="cloudRowStatusDot"></span>
            {{ cloudRowStatusLabel }}
          </div>
          <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
          </svg>
        </template>
        <template v-else>
          <div class="min-w-20 shrink-0 text-right text-xs">
            <span class="relative inline-block">
              <span class="invisible" aria-hidden="true">Configure</span>
              <span class="absolute left-0 top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-3.5 py-1.5 text-xs font-medium text-white transition-all group-hover:from-teal-500 group-hover:via-cyan-400 group-hover:to-indigo-400" :class="{ 'opacity-60': isCloudConnecting }">
                {{ isCloudConnecting ? 'Connecting…' : 'Sign in' }}
              </span>
            </span>
          </div>
          <span class="h-4 w-4 shrink-0" aria-hidden="true"></span>
        </template>
      </button>

      <button
        v-if="comfyProviders.length === 0"
        type="button"
        class="flex w-full items-center gap-4 px-1 py-4 text-left hover:bg-overlay-subtle"
        @click="openComfySetup"
      >
        <ToolProviderBrandIcon kind="comfyui" />
        <div class="min-w-0 flex-1">
          <div class="text-[13px] text-content">ComfyUI</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">Run generation workflows locally.</div>
        </div>
        <div class="min-w-20 shrink-0 text-right text-xs text-accent-hi">Configure</div>
        <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
        </svg>
      </button>

      <button
        v-for="provider in comfyProviders"
        :key="provider.id"
        type="button"
        class="flex w-full items-center gap-4 px-1 py-4 text-left hover:bg-overlay-subtle"
        @click="openProviderDetails(provider.id)"
      >
        <ToolProviderBrandIcon :provider="provider" />
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px]" :class="provider.enabled === false ? 'text-content-muted' : 'text-content'">{{ provider.name }}</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">ComfyUI · {{ provider.url || getProviderTypeLabel(provider.type) }}</div>
        </div>
        <div class="flex min-w-20 shrink-0 items-center justify-end gap-1.5 whitespace-nowrap text-right text-xs" :class="providerRowStatusClass(provider)">
          <Spinner v-if="isProviderConnecting(provider)" size="sm" />
          <ExclamationCircleIcon v-else-if="isProviderConnectionError(provider)" class="h-4 w-4" />
          <span v-else-if="providerStatusDotClass(provider)" class="h-2 w-2 shrink-0 rounded-full" :class="providerStatusDotClass(provider)"></span>
          {{ providerStatusLabel(provider) }}
        </div>
        <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
        </svg>
      </button>

      <button
        v-for="provider in customProviders"
        :key="provider.id"
        type="button"
        class="flex w-full items-center gap-4 px-1 py-4 text-left hover:bg-overlay-subtle"
        @click="openProviderDetails(provider.id)"
      >
        <ToolProviderBrandIcon :provider="provider" />
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px]" :class="provider.enabled === false ? 'text-content-muted' : 'text-content'">{{ provider.name }}</div>
          <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ getProviderTypeLabel(provider.type) }}</div>
        </div>
        <div class="flex min-w-20 shrink-0 items-center justify-end gap-1.5 whitespace-nowrap text-right text-xs" :class="providerRowStatusClass(provider)">
          <Spinner v-if="isProviderConnecting(provider)" size="sm" />
          <ExclamationCircleIcon v-else-if="isProviderConnectionError(provider)" class="h-4 w-4" />
          <span v-else-if="providerStatusDotClass(provider)" class="h-2 w-2 shrink-0 rounded-full" :class="providerStatusDotClass(provider)"></span>
          {{ providerStatusLabel(provider) }}
        </div>
        <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" />
        </svg>
      </button>

      <button
        type="button"
        class="flex w-full items-center gap-4 px-1 py-4 text-left hover:bg-accent/[0.04]"
        @click="openAddModal"
      >
        <span class="flex h-10 w-10 shrink-0 items-center justify-center text-accent-hi">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <path stroke-linecap="round" d="M12 5v14M5 12h14" />
          </svg>
        </span>
        <span class="min-w-0 flex-1">
          <span class="block text-[13px] font-medium text-accent-hi">Add STP Provider</span>
          <span class="mt-0.5 block truncate text-xs text-content-tertiary">
            Connect any server that speaks the
            <a :href="stpDocsUrl" target="_blank" rel="noopener noreferrer" class="text-accent-hi hover:text-accent" @click.stop.prevent="openStpDocs">Stimma Tools Protocol ↗</a>.
          </span>
        </span>
      </button>
    </div>
    </template>

    <section v-else-if="selectedProvider && detailView === 'tools'" class="max-w-3xl">
      <div class="mb-7 flex items-center gap-4">
        <button type="button" class="flex h-9 w-9 shrink-0 items-center justify-center text-content-tertiary hover:text-content" title="Back to provider" @click="closeProviderSubpage">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
        </button>
        <ToolProviderBrandIcon :provider="selectedProvider" />
        <div class="min-w-0 flex-1">
          <h3 class="text-xs font-semibold text-content-secondary">Tools</h3>
          <p class="truncate text-xs text-content-tertiary">{{ selectedProvider.name }}</p>
        </div>
        <span class="text-xs text-content-muted">{{ toolsModal.tools.length }} tool{{ toolsModal.tools.length === 1 ? '' : 's' }}</span>
      </div>

      <input v-model="toolsFilter" type="search" placeholder="Search tools" class="mb-5 w-full border border-edge bg-surface-raised px-3 py-2.5 text-sm text-content placeholder:text-content-muted focus:border-accent focus:outline-none" />

      <div v-if="toolsModal.loading" class="py-10 text-center text-sm text-content-tertiary">Loading tools…</div>
      <div v-else-if="filteredTools.length === 0" class="py-10 text-center text-sm text-content-tertiary">
        {{ toolsFilter ? 'No tools match your search.' : 'No tools available.' }}
      </div>
      <div v-else>
        <div v-for="tool in filteredTools" :key="tool.full_tool_id" class="flex items-start gap-4 py-3.5">
          <div class="min-w-0 flex-1">
            <div class="text-[13px] text-content">{{ tool.name }}</div>
            <p v-if="tool.metadata?.description" class="mt-0.5 line-clamp-2 text-xs leading-5 text-content-tertiary">{{ tool.metadata.description }}</p>
            <div v-if="tool.task_types?.length || tool.task_type" class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-content-muted">
              <span v-for="taskType in (tool.task_types?.length ? tool.task_types : [tool.task_type])" :key="taskType">{{ formatTaskTypeLabel(taskType) }}</span>
            </div>
          </div>
          <button v-if="devModeRef" type="button" class="shrink-0 p-1.5 text-content-muted hover:text-content" :title="copiedToolId === tool.full_tool_id ? 'Copied' : 'Copy raw JSON'" @click="copyToolJson(tool.full_tool_id)">
            <svg v-if="copiedToolId === tool.full_tool_id" class="h-4 w-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="m5 13 4 4L19 7" /></svg>
            <svg v-else class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2m-6 12h8a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2Z" /></svg>
          </button>
        </div>
      </div>
    </section>

    <section v-else-if="selectedProvider && detailView === 'logs'" class="max-w-3xl">
      <div class="mb-7 flex items-center gap-4">
        <button type="button" class="flex h-9 w-9 shrink-0 items-center justify-center text-content-tertiary hover:text-content" title="Back to provider" @click="closeProviderSubpage">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
        </button>
        <ToolProviderBrandIcon :provider="selectedProvider" />
        <div class="min-w-0 flex-1">
          <h3 class="text-xs font-semibold text-content-secondary">Logs</h3>
          <p class="truncate text-xs text-content-tertiary">{{ selectedProvider.name }}</p>
        </div>
        <button type="button" :disabled="logsModal.loading" class="text-[13px] text-accent-hi hover:text-accent disabled:opacity-50" @click="refreshLogs">Refresh</button>
        <button type="button" class="text-sm text-content-tertiary hover:text-content" @click="clearLogsDisplay">Clear</button>
      </div>

      <div ref="logsContentRef" class="max-h-[60vh] min-h-72 overflow-auto bg-overlay-medium p-4">
        <div v-if="logsModal.loading && logsModal.lines.length === 0" class="py-10 text-center text-sm text-content-tertiary">Loading logs…</div>
        <div v-else-if="logsModal.lines.length === 0" class="py-10 text-center text-sm text-content-tertiary">No logs available.</div>
        <pre v-else class="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-content-secondary select-text">{{ logsModal.lines.join('\n') }}</pre>
      </div>
    </section>

    <section v-else-if="selectedProvider">
      <div class="mb-7 flex max-w-2xl items-center gap-4">
        <button
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center text-content-tertiary hover:text-content"
          title="Back to Generation Tools"
          @click="closeProviderDetails"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
            <path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <ToolProviderBrandIcon :provider="selectedProvider" />
        <div class="min-w-0 flex-1">
          <h3 class="truncate text-[16px] font-semibold text-content">{{ selectedProvider.name }}</h3>
          <p class="truncate text-xs text-content-tertiary">
            {{ selectedProvider.id === 'stimma-cloud'
              ? 'Hosted generation tools'
              : isComfyUIProvider(selectedProvider)
                ? 'Local generation tools'
                : getProviderTypeLabel(selectedProvider.type) }}
          </p>
        </div>
        <span class="flex items-center gap-1.5 text-xs font-medium" :class="providerConnectionStatusClass(selectedProvider)">
          <Spinner v-if="isProviderConnecting(selectedProvider)" size="sm" />
          <ExclamationCircleIcon v-else-if="isProviderConnectionError(selectedProvider)" class="h-4 w-4" />
          <span v-else-if="providerStatusDotClass(selectedProvider)" class="h-2 w-2 shrink-0 rounded-full" :class="providerStatusDotClass(selectedProvider)"></span>
          {{ providerConnectionStatus(selectedProvider) }}
        </span>
      </div>

      <div v-if="selectedProvider.error_message" class="mb-7 flex max-w-2xl items-start gap-3 rounded-lg bg-red-500/10 px-4 py-3.5">
        <svg class="mt-0.5 h-5 w-5 shrink-0 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-1.5a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12V16.5Z" />
        </svg>
        <div class="min-w-0">
          <p class="text-sm font-medium text-red-300">{{ formattedSelectedProviderError.title }}</p>
          <p class="mt-0.5 text-xs leading-5 text-content-secondary">{{ formattedSelectedProviderError.message }}</p>
        </div>
      </div>

      <template v-if="selectedProvider.id === 'stimma-cloud'">
        <div v-if="!isAuthenticated" class="space-y-5">
          <p class="max-w-xl text-sm leading-6 text-content-tertiary">Buy credits to use image, video, audio, and other generation tools from many providers.</p>
          <button
            type="button"
            :disabled="isCloudConnecting"
            class="bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-4 py-2 text-sm font-medium text-white transition-all hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 disabled:opacity-60"
            @click="handleCloudConnect"
          >
            {{ isCloudConnecting ? 'Connecting...' : 'Sign in to Stimma' }}
          </button>
        </div>
        <div v-else class="max-w-2xl space-y-5">
          <div class="flex items-center justify-between gap-6 py-2">
            <div>
              <div class="text-[13px] text-content">Credits</div>
              <div class="mt-0.5 text-xs text-content-tertiary">Used across Stimma generation tools and hosted models.</div>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <span class="text-[13px] text-content">{{ formatBalance(cloudUser?.credits) || '$0.00' }}</span>
              <a :href="cloudBaseUrl + '/link/addcredits'" target="_blank" class="text-[13px] text-accent-hi hover:underline">Add credits</a>
            </div>
          </div>
        </div>
      </template>

      <div v-else-if="isComfyUIProvider(selectedProvider)" class="max-w-2xl space-y-5">
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">Name</label>
          <input :value="getEditValue(selectedProvider.id, 'name') ?? selectedProvider.name" type="text" class="w-full border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" @input="setEditValue(selectedProvider.id, 'name', $event.target.value)" @blur="saveInlineEdit(selectedProvider.id, 'name')" />
        </div>
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">WebSocket URL</label>
          <input :value="getEditValue(selectedProvider.id, 'url') ?? selectedProvider.url ?? ''" type="text" class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none" @input="setEditValue(selectedProvider.id, 'url', $event.target.value)" @blur="saveInlineEdit(selectedProvider.id, 'url')" />
        </div>
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">Token <span class="text-content-muted">(optional)</span></label>
          <input :value="getEditValue(selectedProvider.id, 'auth_token') ?? selectedProvider.auth_token ?? ''" type="password" autocomplete="off" class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none" @input="setEditValue(selectedProvider.id, 'auth_token', $event.target.value)" @blur="saveInlineEdit(selectedProvider.id, 'auth_token')" />
        </div>
        <div class="flex justify-end">
          <button type="button" :disabled="testing" class="text-[13px] text-accent-hi hover:text-accent disabled:opacity-50" @click="testExistingProvider(selectedProvider)">{{ testing ? 'Testing…' : 'Test connection' }}</button>
        </div>
      </div>

      <div v-else class="max-w-2xl space-y-5">
        <div>
          <label class="mb-1 block text-xs text-content-tertiary">Name</label>
          <input
            :value="getEditValue(selectedProvider.id, 'name') ?? selectedProvider.name"
            type="text"
            class="w-full border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none"
            @input="setEditValue(selectedProvider.id, 'name', $event.target.value)"
            @blur="saveInlineEdit(selectedProvider.id, 'name')"
          />
        </div>

        <template v-if="selectedProvider.type === 'builtin' && selectedProvider.id === 'gemini'">
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">API key</label>
            <input
              :value="getEditValue(selectedProvider.id, 'api_key') ?? selectedProvider.api_key ?? '${GEMINI_API_KEY}'"
              type="text"
              placeholder="${GEMINI_API_KEY}"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'api_key', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'api_key')"
            />
            <p class="mt-1 text-xs text-content-muted">Use ${GEMINI_API_KEY} to read from an environment variable.</p>
          </div>
        </template>

        <template v-if="selectedProvider.type === 'stdio'">
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Command</label>
            <input
              :value="getEditValue(selectedProvider.id, 'command') ?? selectedProvider.command ?? ''"
              type="text"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'command', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'command')"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Arguments</label>
            <input
              :value="getEditValue(selectedProvider.id, 'args') ?? serializeArgs(selectedProvider.args) ?? ''"
              type="text"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'args', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'args')"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Working directory</label>
            <input
              :value="getEditValue(selectedProvider.id, 'working_dir') ?? selectedProvider.working_dir ?? ''"
              type="text"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'working_dir', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'working_dir')"
            />
          </div>
        </template>

        <template v-if="selectedProvider.type === 'websocket'">
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">WebSocket URL</label>
            <input
              :value="getEditValue(selectedProvider.id, 'url') ?? selectedProvider.url ?? ''"
              type="text"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'url', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'url')"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Token</label>
            <input
              :value="getEditValue(selectedProvider.id, 'auth_token') ?? selectedProvider.auth_token ?? ''"
              type="password"
              autocomplete="off"
              class="w-full border border-edge bg-surface-raised px-3 py-2 font-mono text-sm text-content focus:border-accent focus:outline-none"
              @input="setEditValue(selectedProvider.id, 'auth_token', $event.target.value)"
              @blur="saveInlineEdit(selectedProvider.id, 'auth_token')"
            />
          </div>
        </template>

        <div v-if="selectedProvider.type === 'stdio' || selectedProvider.type === 'websocket'" class="flex justify-end">
          <button type="button" :disabled="testing" class="text-[13px] text-accent-hi hover:text-accent disabled:opacity-50" @click="testExistingProvider(selectedProvider)">{{ testing ? 'Testing…' : 'Test connection' }}</button>
        </div>
      </div>

      <div v-if="selectedProvider.id !== 'stimma-cloud' || isAuthenticated" class="mt-8 max-w-2xl space-y-1">
        <button type="button" class="flex w-full items-center gap-4 py-3 text-left hover:bg-overlay-subtle" @click="openProviderToolsPage(selectedProvider)">
          <div class="min-w-0 flex-1">
            <div class="text-[13px] text-content">Tools</div>
            <div class="mt-0.5 text-xs text-content-tertiary">{{ selectedProvider.tool_count || 0 }} available</div>
          </div>
          <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" /></svg>
        </button>

        <button v-if="selectedProvider.type === 'stdio' || selectedProvider.type === 'websocket'" type="button" class="flex w-full items-center gap-4 py-3 text-left hover:bg-overlay-subtle" @click="openProviderLogsPage(selectedProvider)">
          <div class="min-w-0 flex-1">
            <div class="text-[13px] text-content">Logs</div>
            <div class="mt-0.5 text-xs text-content-tertiary">Connection and provider output</div>
          </div>
          <svg class="h-4 w-4 shrink-0 text-content-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" /></svg>
        </button>

        <div v-if="isComfyUIProvider(selectedProvider)" class="flex items-center justify-between gap-6 py-3">
          <div>
            <div class="text-[13px] text-content">ComfyUI setup</div>
            <div class="mt-0.5 text-xs text-content-tertiary">Install or update the Stimma extension.</div>
          </div>
          <a :href="comfyUiDocsUrl" target="_blank" rel="noopener noreferrer" class="shrink-0 text-[13px] text-accent-hi hover:text-accent" @click.prevent="openComfyUiDocs">Setup guide ↗</a>
        </div>

        <div v-if="!wizard" class="flex items-center justify-end gap-5 pt-6">
          <button type="button" class="text-sm text-content-tertiary hover:text-content" @click="toggleProviderFromDetail(selectedProvider)">{{ selectedProvider.enabled === false ? 'Enable' : 'Disable' }}</button>
          <button v-if="selectedProvider.id !== 'stimma-cloud' && selectedProvider.type !== 'builtin'" type="button" class="text-sm text-red-400 hover:text-red-300" @click="confirmDelete(selectedProvider)">Remove provider</button>
        </div>
      </div>
    </section>

    <!-- Add provider drilldown -->
    <div v-if="showModal" ref="addModalRef" class="max-w-2xl" tabindex="-1">
      <div class="mb-7 flex items-center gap-4">
        <button type="button" class="flex h-9 w-9 shrink-0 items-center justify-center text-content-tertiary hover:text-content" title="Back to Generation Tools" @click="closeModal">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
        </button>
        <ToolProviderBrandIcon :kind="addMode === 'comfy' ? 'comfyui' : 'custom'" />
        <div>
          <h3 class="text-xs font-semibold text-content-secondary">{{ addMode === 'comfy' ? 'Set up ComfyUI' : 'Add Provider' }}</h3>
          <p class="text-xs text-content-tertiary">{{ addMode === 'comfy' ? 'Run generation tools on your own computer.' : 'For STP servers you’re developing or running yourself.' }}</p>
        </div>
      </div>

      <template v-if="addMode === 'comfy'">
        <div class="space-y-1">
          <div class="flex gap-4 py-3">
            <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent-hi">1</span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] text-content">Install the Stimma extension in ComfyUI</div>
              <p class="mt-1 text-sm leading-6 text-content-tertiary">The extension lets Stimma discover and run your ComfyUI workflows.</p>
              <a :href="comfyUiDocsUrl" target="_blank" rel="noopener noreferrer" class="mt-2 inline-flex text-sm font-medium text-accent-hi hover:text-accent" @click.prevent="openComfyUiDocs">Open the ComfyUI setup guide ↗</a>
            </div>
          </div>
          <div class="flex gap-4 py-3">
            <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent-hi">2</span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] text-content">Start ComfyUI</div>
              <p class="mt-1 text-sm leading-6 text-content-tertiary">Leave it running while Stimma connects.</p>
            </div>
          </div>
          <div class="flex gap-4 py-3">
            <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent-hi">3</span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] text-content">Connect</div>
              <label class="mt-4 block text-xs text-content-tertiary">ComfyUI address</label>
              <input v-model="formData.url" type="text" class="mt-1.5 w-full border border-edge bg-surface-raised px-3 py-2.5 font-mono text-sm text-content focus:border-accent focus:outline-none" />
              <p class="mt-2 text-xs text-content-muted">The default works with ComfyUI running on this computer.</p>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="space-y-5">
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Name</label>
            <input v-model="formData.name" type="text" placeholder="My provider" class="w-full border border-edge bg-surface-raised px-3 py-2.5 text-sm text-content focus:border-accent focus:outline-none" />
            <p v-if="nameError" class="mt-1 text-xs text-red-500">{{ nameError }}</p>
          </div>
          <div>
            <label class="mb-1 block text-xs text-content-tertiary">Connection</label>
            <div class="inline-flex border border-edge bg-surface-raised p-1 text-xs">
              <button type="button" class="px-3 py-1.5" :class="formData.type === 'websocket' ? 'bg-accent/10 text-accent-hi' : 'text-content-tertiary'" @click="formData.type = 'websocket'">WebSocket</button>
              <button type="button" class="px-3 py-1.5" :class="formData.type === 'stdio' ? 'bg-accent/10 text-accent-hi' : 'text-content-tertiary'" @click="formData.type = 'stdio'">Command</button>
            </div>
          </div>
          <template v-if="formData.type === 'stdio'">
            <div><label class="mb-1 block text-xs text-content-tertiary">Command</label><input v-model="formData.command" type="text" placeholder="/path/to/tool" class="w-full border border-edge bg-surface-raised px-3 py-2.5 text-sm text-content focus:border-accent focus:outline-none" /></div>
            <div><label class="mb-1 block text-xs text-content-tertiary">Arguments</label><input v-model="formData.args" type="text" placeholder="--port 8080" class="w-full border border-edge bg-surface-raised px-3 py-2.5 font-mono text-sm text-content focus:border-accent focus:outline-none" /></div>
            <div><label class="mb-1 block text-xs text-content-tertiary">Working directory</label><input v-model="formData.working_dir" type="text" placeholder="Optional" class="w-full border border-edge bg-surface-raised px-3 py-2.5 font-mono text-sm text-content focus:border-accent focus:outline-none" /></div>
          </template>
          <template v-else>
            <div><label class="mb-1 block text-xs text-content-tertiary">WebSocket URL</label><input v-model="formData.url" type="text" placeholder="ws://localhost:9000/stp-v1" class="w-full border border-edge bg-surface-raised px-3 py-2.5 font-mono text-sm text-content focus:border-accent focus:outline-none" /></div>
            <div><label class="mb-1 block text-xs text-content-tertiary">Token</label><input v-model="formData.auth_token" type="text" placeholder="Optional bearer token" class="w-full border border-edge bg-surface-raised px-3 py-2.5 font-mono text-sm text-content focus:border-accent focus:outline-none" /></div>
          </template>
        </div>
      </template>

      <div v-if="testResult" class="mt-5 rounded-lg px-4 py-3" :class="testResult.success ? 'bg-green-500/10' : 'bg-red-500/10'">
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
            <div v-else class="flex items-start gap-3">
              <svg class="mt-0.5 h-5 w-5 shrink-0 text-red-400" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-1.5a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12V16.5Z" />
              </svg>
              <div class="min-w-0">
                <p class="text-sm font-medium text-red-300">{{ formattedTestResultError.title }}</p>
                <p class="mt-0.5 text-xs leading-5 text-content-secondary">{{ formattedTestResultError.message }}</p>
              </div>
            </div>
      </div>

      <div class="mt-6 flex items-center gap-3">
        <button
          v-if="addMode === 'comfy'"
          type="button"
          :disabled="!canTest || testing || saving"
          class="bg-accent rounded-md px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
          @click="connectComfyProvider"
        >{{ testing ? 'Testing…' : saving ? 'Adding…' : 'Test and connect' }}</button>
        <template v-else>
          <button type="button" :disabled="!canTest || testing" class="bg-surface-raised px-4 py-2 text-sm font-medium text-content hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50" @click="testConnection">{{ testing ? 'Testing…' : 'Test connection' }}</button>
          <button type="button" :disabled="!canSave || saving" class="bg-accent rounded-md px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50" @click="saveProvider">{{ saving ? 'Adding…' : 'Add provider' }}</button>
        </template>
        <button type="button" class="px-3 py-2 text-sm text-content-tertiary hover:text-content" @click="closeModal">Cancel</button>
      </div>
    </div>

    <!-- Delete confirmation modal -->
    <ConfirmDialog
      :show="!!deleteConfirm"
      title="Remove tool provider"
      :confirm-label="saving ? 'Removing...' : 'Remove'"
      danger
      :busy="saving"
      @confirm="deleteTool"
      @cancel="deleteConfirm = null"
    >
      <template v-if="deleteConfirm">
        Are you sure you want to remove <strong class="text-content">{{ deleteConfirm.name }}</strong>?
      </template>
    </ConfirmDialog>

    <!-- Logs modal -->
    <Modal
      :show="!!logsModal.provider && detailView !== 'logs'"
      size="custom"
      custom-class="w-[700px] max-w-[90vw] max-h-[80vh] flex flex-col"
      @close="closeLogsModal"
    >
      <template #header>
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-lg font-semibold text-content">Process logs</h3>
            <p class="text-xs text-content-tertiary">{{ logsModal.provider?.name }}</p>
          </div>
            <div class="flex items-center gap-2">
              <button
                @click="refreshLogs"
                :disabled="logsModal.loading"
                class="px-3 py-1.5 bg-surface-raised hover:bg-surface-hover disabled:opacity-50 text-content rounded font-medium text-sm transition-colors flex items-center gap-1.5"
              >
                <Spinner v-if="logsModal.loading" size="sm" />
                <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
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
      </template>

      <!-- Log content -->
      <div class="flex-1 overflow-auto p-4 min-h-[300px]" ref="logsContentRef">
        <div v-if="logsModal.loading && logsModal.lines.length === 0" class="text-center text-content-tertiary py-8">
          Loading logs...
        </div>
        <div v-else-if="logsModal.lines.length === 0" class="text-center text-content-tertiary py-8">
          No logs available
        </div>
        <pre v-else class="text-xs font-mono text-content-secondary whitespace-pre-wrap break-words select-text">{{ logsModal.lines.join('\n') }}</pre>
      </div>

      <!-- Line count -->
      <div class="px-4 py-2 border-t border-edge text-xs text-content-muted">
        Showing {{ logsModal.lines.length }} of {{ logsModal.totalLines }} lines
      </div>
    </Modal>

    <!-- Tools modal -->
    <Modal
      :show="!!toolsModal.provider && detailView !== 'tools'"
      size="custom"
      custom-class="w-[600px] max-w-[90vw] max-h-[80vh] flex flex-col"
      @close="closeToolsModal"
    >
      <template #header>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
              <div>
                <h3 class="text-[16px] font-semibold text-content">Available Tools</h3>
                <p class="text-xs text-content-tertiary">{{ toolsModal.provider?.name }}</p>
                <!-- Dev mode: Provider registration info -->
                <div v-if="devModeRef && toolsModal.provider" class="mt-1 text-xs font-mono text-content-muted bg-overlay-subtle rounded px-2 py-1">
                  <span class="text-content-tertiary">max_concurrent:</span> {{ toolsModal.provider.max_concurrent ?? 'N/A' }}
                  <span v-if="toolsModal.provider.queue_status" class="ml-2">
                    <span class="text-content-muted">|</span>
                    <span class="text-green-500 ml-2">running:</span> {{ toolsModal.provider.queue_status.running ?? 0 }}
                    <span class="text-amber-400 ml-2">queued:</span> {{ toolsModal.provider.queue_status.queued ?? 0 }}
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
      </template>

      <!-- Search filter -->
      <div class="px-4 py-2 border-b border-edge">
        <input
          v-model="toolsFilter"
          type="text"
          placeholder="Filter tools..."
          class="w-full bg-overlay-subtle border border-transparent rounded-md px-3 py-1.5 text-sm text-content placeholder:text-content-muted focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
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
                    <h4 class="text-[13px] text-content">{{ tool.name }}</h4>
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

      <!-- Tool count -->
      <div class="px-4 py-2 border-t border-edge text-xs text-content-muted">
        <template v-if="toolsFilter && filteredTools.length !== toolsModal.tools.length">
          {{ filteredTools.length }} of {{ toolsModal.tools.length }} tools
        </template>
        <template v-else>
          {{ toolsModal.tools.length }} tool{{ toolsModal.tools.length !== 1 ? 's' : '' }}
        </template>
      </div>
    </Modal>

    <!-- Cloud menu dropdown (teleported to avoid overflow clipping) -->
    <Teleport to="body">
      <div
        v-if="showCloudMenu && cloudMenuPosition"
        data-cloud-menu
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-menu"
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
        class="fixed bg-surface border border-edge rounded-lg shadow-lg py-1 min-w-[140px] z-menu"
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
import { ExclamationCircleIcon } from '@heroicons/vue/24/outline'
import Spinner from '../../ui/Spinner.vue'
import Modal from '../../ui/Modal.vue'
import ConfirmDialog from '../../ui/ConfirmDialog.vue'
import { useAuth } from '../../../composables/useAuth'
import { useCloudAccount, formatBalance } from '../../../composables/useCloudAccount'
import { copyToClipboard } from '../../../utils/clipboard'
import { addToast } from '../../../composables/useToasts'
import { devModeRef } from '../../../appConfig'
import { formatTaskTypeLabel } from '../../../utils/taskTypeIcons'
import { STIMMA_TOOL_PROVIDER_DISPLAY_NAME } from '../../../utils/stimmaCloud'
import { DEFAULT_COMFYUI_STP_URL, isComfyUIProvider, nextComfyUIIdentity } from '../../../utils/toolProviderBrands'
import { formatToolProviderConnectionError } from '../../../utils/toolProviderErrors'
import ToolProviderBrandIcon from '../../tools/ToolProviderBrandIcon.vue'

const props = defineProps({
  providers: {
    type: Array,
    default: () => []
  },
  setupRequired: {
    type: Boolean,
    default: false
  },
  // Setup-wizard variant: no section header/description/banner; rows and
  // connect flows are unchanged.
  wizard: {
    type: Boolean,
    default: false
  }
})

// Auth and cloud account state
const { user, isAuthenticated, signInWithBrowser } = useAuth()
const { cloudBaseUrl, cloudUser, fetchCloudAccount, ensureCloudBaseUrl } = useCloudAccount()
const comfyUiDocsUrl = 'https://stimma.ai/link/comfyui'
const stpDocsUrl = 'https://stimma.ai/link/stp'

async function openExternalDocs(url) {
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

// The zero-balance row reads "Add credits" — clicking it must go to the web
// dashboard, not the provider detail screen.
async function openAddCredits() {
  await ensureCloudBaseUrl()
  await openExternalDocs(`${cloudBaseUrl.value}/link/addcredits`)
}

async function openComfyUiDocs() {
  await openExternalDocs(comfyUiDocsUrl)
}

async function openStpDocs() {
  await openExternalDocs(stpDocsUrl)
}

// Signed-out Connect button on the built-in Stimma provider card
const isCloudConnecting = ref(false)

async function handleCloudConnect() {
  isCloudConnecting.value = true
  try {
    await signInWithBrowser(props.wizard ? 'create' : undefined)
  } catch (error) {
    addToast(error.message || 'Connection failed', 'error')
  } finally {
    isCloudConnecting.value = false
  }
}

// Cloud dashboard URL
const cloudDashboardUrl = computed(() => cloudBaseUrl.value + '/link/dashboard')

// Cloud provider from the providers list
const cloudProvider = computed(() => {
  return props.providers.find(p => p.id === 'stimma-cloud')
})

// The cloud provider stays connected for any signed-in account (access is
// enforced per-request by balance on the cloud side), so a connected
// zero-balance account must read as "Add credits", not as a tool count.
const cloudNeedsCredits = computed(() => (
  cloudUser.value != null && Number(cloudUser.value.credits ?? 0) <= 0
))
const cloudConnectedWithoutCredits = computed(() => (
  cloudNeedsCredits.value
  && cloudProvider.value?.enabled !== false
  && cloudProvider.value?.status === 'connected'
))
const cloudReady = computed(() => (
  !cloudNeedsCredits.value
  && cloudProvider.value?.enabled !== false
  && cloudProvider.value?.status === 'connected'
))
const cloudRowStatusLabel = computed(() => {
  if (cloudConnectedWithoutCredits.value) return 'Add credits'
  if (cloudReady.value) return `Ready · ${providerStatusLabel(cloudProvider.value)}`
  return providerStatusLabel(cloudProvider.value)
})
// Status words stay neutral; the dot carries the color (no naked colored text).
const cloudRowStatusClass = computed(() => {
  if (cloudConnectedWithoutCredits.value || cloudReady.value) return 'text-content-tertiary'
  return providerRowStatusClass(cloudProvider.value)
})
const cloudRowStatusDot = computed(() => {
  if (cloudConnectedWithoutCredits.value) return 'bg-amber-400'
  if (cloudReady.value) return 'bg-green-500'
  return null
})

const configurableProviders = computed(() => props.providers.filter(provider => provider.id !== 'stimma-cloud'))
const comfyProviders = computed(() => configurableProviders.value.filter(isComfyUIProvider))
const customProviders = computed(() => configurableProviders.value.filter(provider => !isComfyUIProvider(provider)))
const stimmaProviderDescription = computed(() => {
  if (!isAuthenticated.value) return 'A complete toolkit powered by one pool of credits.'
  return 'Over 50 hosted image, video, and audio tools'
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
    openToolsModal({ ...provider, name: STIMMA_TOOL_PROVIDER_DISPLAY_NAME })
  }
}

const emit = defineEmits(['update', 'create', 'delete'])

const saving = ref(false)
const togglingProvider = ref(null)
const showModal = ref(false)
const addMode = ref('custom')
const selectedProviderId = ref(null)
const detailView = ref('overview')
const deleteConfirm = ref(null)
const testing = ref(false)
const testResult = ref(null)
const addModalRef = ref(null)
const logsContentRef = ref(null)
const nameInputRef = ref(null)

const selectedProvider = computed(() => {
  if (!selectedProviderId.value) return null
  if (selectedProviderId.value === 'stimma-cloud') {
    return cloudProvider.value || {
      id: 'stimma-cloud',
      name: STIMMA_TOOL_PROVIDER_DISPLAY_NAME,
      type: 'websocket',
      enabled: true,
      status: 'disconnected',
      tool_count: 0,
      error_message: null,
    }
  }
  return props.providers.find(provider => provider.id === selectedProviderId.value) || null
})

const formattedSelectedProviderError = computed(() => formatToolProviderConnectionError(
  selectedProvider.value?.error_message,
  selectedProvider.value?.url,
))

function providerStatusDotClass(provider) {
  if (!provider || provider.enabled === false) return 'bg-zinc-500'
  if (provider.status === 'connected') return 'bg-green-500'
  if (provider.status === 'connecting') return 'bg-amber-400'
  if (isProviderConnectionError(provider)) return 'bg-red-500'
  if (provider.status === 'disconnected') return 'bg-amber-400'
  return 'bg-zinc-500'
}

function providerStatusLabel(provider) {
  if (!provider) return 'Not connected'
  if (provider.enabled === false) return 'Disabled'
  if (provider.status === 'connecting') return 'Connecting'
  if (provider.status === 'connected') {
    const count = Number(provider.tool_count || 0)
    return `${count} tool${count === 1 ? '' : 's'}`
  }
  if (provider.error_message) return providerConnectionErrorTitle(provider)
  if (provider.status === 'error') return 'Connection failed'
  return 'Not connected'
}

function isProviderConnecting(provider) {
  return provider?.enabled !== false && provider?.status === 'connecting'
}

function isProviderConnectionError(provider) {
  return provider?.enabled !== false
    && provider?.status !== 'connecting'
    && provider?.status !== 'connected'
    && (provider?.status === 'error' || Boolean(provider?.error_message))
}

function providerConnectionErrorTitle(provider) {
  return formatToolProviderConnectionError(provider?.error_message, provider?.url).title
}

function providerRowStatusClass(provider) {
  if (provider?.enabled === false) return 'text-content-muted'
  if (provider?.status === 'connecting') return 'text-content-tertiary'
  if (isProviderConnectionError(provider)) return 'text-red-400'
  return 'text-content-muted'
}

function openProviderDetails(providerId) {
  closeCloudMenu()
  closeProviderMenu()
  showModal.value = false
  detailView.value = 'overview'
  selectedProviderId.value = providerId
}

function closeProviderDetails() {
  closeCloudMenu()
  closeProviderMenu()
  closeToolsModal()
  closeLogsModal()
  detailView.value = 'overview'
  selectedProviderId.value = null
}

function providerConnectionStatus(provider) {
  if (provider?.id === 'stimma-cloud' && !isAuthenticated.value) return 'Not signed in'
  if (provider?.enabled === false) return 'Disabled'
  if (provider?.status === 'connecting') return 'Connecting'
  if (provider?.status === 'connected') return 'Connected'
  if (provider?.error_message) return providerConnectionErrorTitle(provider)
  if (provider?.status === 'error') return 'Connection failed'
  return 'Not connected'
}

function providerConnectionStatusClass(provider) {
  if (provider?.enabled === false) return 'text-content-muted'
  if (provider?.status === 'connected') return 'text-content-tertiary'
  if (provider?.status === 'connecting') return 'text-content-tertiary'
  if (isProviderConnectionError(provider)) return 'text-red-400'
  return provider?.id === 'stimma-cloud' && !isAuthenticated.value ? 'text-accent-hi' : 'text-content-muted'
}

async function openProviderToolsPage(provider) {
  detailView.value = 'tools'
  await openToolsModal(provider)
}

async function openProviderLogsPage(provider) {
  detailView.value = 'logs'
  await openLogsModal(provider)
}

function closeProviderSubpage() {
  if (detailView.value === 'tools') closeToolsModal()
  if (detailView.value === 'logs') closeLogsModal()
  detailView.value = 'overview'
}

function toggleProviderFromDetail(provider) {
  if (provider.id === 'stimma-cloud') {
    toggleCloudEnabled()
    return
  }
  toggleEnabled(provider.id, provider.enabled === false)
}

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
  const provider = cloudProvider.value || { id: 'stimma-cloud' }
  openLogsModal({ ...provider, name: STIMMA_TOOL_PROVIDER_DISPLAY_NAME })
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

// Focus the add-provider drilldown when opened so it can capture Escape
watch(showModal, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    addModalRef.value?.focus()
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

const formattedTestResultError = computed(() => formatToolProviderConnectionError(
  testResult.value?.error,
  formData.value.url,
))

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
  if (!canTest.value || testing.value) return false

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
    return testResult.value.success === true
  } catch (err) {
    testResult.value = {
      success: false,
      error: `Network error: ${err.message}`,
      error_type: 'network',
    }
    return false
  } finally {
    testing.value = false
  }
}

async function testExistingProvider(provider) {
  if (!provider || testing.value) return
  testing.value = true
  try {
    const body = { type: provider.type }
    if (provider.type === 'stdio') {
      body.command = provider.command
      if (provider.args?.length) body.args = provider.args
      if (provider.working_dir) body.working_dir = provider.working_dir
    } else {
      body.url = provider.url
      if (provider.auth_token) body.auth_token = provider.auth_token
    }
    const response = await fetch('/api/tools/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const result = await response.json()
    if (result.success) {
      addToast(`Connected${result.tool_count != null ? ` · ${result.tool_count} tools` : ''}`, 'success')
    } else {
      const formattedError = formatToolProviderConnectionError(result.error, provider.url)
      addToast(formattedError.message, 'error')
    }
  } catch (error) {
    const formattedError = formatToolProviderConnectionError(error.message, provider.url)
    addToast(formattedError.message, 'error')
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
  closeProviderDetails()
  addMode.value = 'custom'
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

function openComfySetup() {
  closeProviderDetails()
  addMode.value = 'comfy'
  const identity = nextComfyUIIdentity(props.providers)
  formData.value = {
    type: 'websocket',
    name: identity.name,
    command: '',
    args: '',
    working_dir: '',
    url: DEFAULT_COMFYUI_STP_URL,
    auth_token: '',
  }
  testResult.value = null
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

function handleEscape() {
  if (showModal.value) {
    closeModal()
    return true
  }
  if (detailView.value !== 'overview') {
    closeProviderSubpage()
    return true
  }
  if (selectedProvider.value) {
    closeProviderDetails()
    return true
  }
  return false
}

defineExpose({ handleEscape })

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

async function connectComfyProvider() {
  const connected = await testConnection()
  if (connected) await saveProvider()
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
    closeProviderDetails()
  } finally {
    saving.value = false
  }
}
</script>
