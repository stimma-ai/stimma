<template>
  <div class="flex flex-col h-full bg-base relative">
    <!-- Control Strip (top bar) - suppressed when embedded -->
    <ChatControlStrip
      v-if="!embedded"
      :chat-name="chat?.name || ''"
      :chat-id="chatId"
      :view-mode="viewMode"
      :settings-panel-visible="settingsPanelVisible"
      @toggle-view="toggleView"
      @toggle-settings-panel="toggleSettingsPanel"
      @delete="confirmDelete"
      @clone="cloneChat"
      @clear="clearChat"
      @rename="renameChatFromStrip"
    />

    <!-- Content area: chat + settings row, with optional image strip below -->
    <div class="flex flex-1 flex-col min-h-0">
      <!-- Chat + Settings horizontal row -->
      <div class="flex flex-1 min-h-0">
        <!-- Main chat area -->
        <div class="flex-1 flex flex-col min-w-0">
    <!-- Chat Messages Area -->
    <div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-4 custom-scrollbar" ref="messagesContainer">
      <!-- Connection Error -->
      <ConnectionError
        v-if="loadError"
        @retry="reloadAll"
      />

      <div v-else-if="loading" class="text-content-tertiary text-center">
        Loading chat...
      </div>

      <template v-else>
        <div v-if="showNoModelSetupHero" class="max-w-xl mx-auto mt-8 rounded-xl border border-edge bg-surface-elevated">
          <div class="p-5">
            <div class="flex items-start gap-3 mb-4">
              <div class="p-2 rounded-lg bg-teal-600/15 flex-shrink-0">
                <SparklesIcon class="w-5 h-5 text-teal-400" />
              </div>
              <div class="min-w-0 text-left">
                <h3 class="text-base font-semibold text-content">Choose a model for this chat</h3>
                <p class="text-sm text-content-tertiary mt-1 leading-relaxed">
                  Sign in to Stimma Cloud for hosted agent models, or connect a local OpenAI-compatible endpoint.
                </p>
              </div>
            </div>
            <div class="space-y-2">
              <button
                type="button"
                @click="handleCloudSignIn"
                :disabled="cloudSigningIn"
                class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 text-sm font-medium text-white hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 disabled:opacity-60 disabled:cursor-wait transition-colors"
              >
                <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
                </svg>
                {{ cloudSigningIn ? 'Opening sign in...' : 'Sign in to Stimma Cloud' }}
              </button>
              <button
                type="button"
                @click="openAISettings"
                class="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-edge text-sm text-content-secondary hover:text-content hover:bg-surface-raised transition-colors"
              >
                <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7m0 0a3 3 0 0 1-3 3" />
                </svg>
                Configure local endpoint
              </button>
            </div>
          </div>
        </div>

        <div v-if="items.length === 0 && !showNoModelSetupHero" class="text-content-tertiary text-center mt-8">
          Start a conversation...
        </div>

      <div v-if="items.length > 0">
        <!-- Load more trigger (scroll-based) -->
        <div v-if="hasMore" ref="loadMoreSentinel" class="text-center mb-4 py-2">
          <span class="text-content-tertiary text-sm">Loading older messages...</span>
        </div>

        <!-- Raw JSON View -->
        <div v-if="viewMode === 'raw'" class="space-y-2">
          <!-- System Prompt Bubble (collapsible) -->
          <div v-if="debugSystemPrompt" class="bg-base border border-blue-500/30 rounded overflow-hidden">
            <div class="flex items-center justify-between px-3 py-2">
              <button
                @click="systemPromptExpanded = !systemPromptExpanded"
                class="flex-1 flex items-center justify-between text-left hover:bg-surface -mx-3 -my-2 px-3 py-2 transition-colors"
              >
                <div class="flex items-center gap-2">
                  <span class="text-xs font-medium text-blue-500">System Prompt</span>
                  <span
                    v-if="debugAgentVersion"
                    class="text-[10px] px-1.5 py-0.5 rounded border bg-blue-500/15 border-blue-500/50 text-blue-400"
                  >
                    {{ debugAgentVersion.toUpperCase() }}
                  </span>
                </div>
                <div class="flex items-center gap-2 text-content-muted text-[10px]">
                  <span>{{ debugSystemPrompt.length.toLocaleString() }} chars</span>
                  <ChevronDownIcon v-if="!systemPromptExpanded" class="w-4 h-4" />
                  <ChevronUpIcon v-else class="w-4 h-4" />
                </div>
              </button>
              <button
                @click.stop="copySystemPrompt"
                class="ml-2 p-1 rounded hover:bg-surface-raised text-content-muted hover:text-content-secondary transition-colors"
                title="Copy system prompt to clipboard"
              >
                <ClipboardDocumentListIcon class="w-4 h-4" />
              </button>
            </div>
            <div v-if="systemPromptExpanded" class="border-t border-edge p-3 max-h-[60vh] overflow-y-auto">
              <pre class="text-[11px] text-content-secondary whitespace-pre-wrap font-mono">{{ debugSystemPrompt }}</pre>
            </div>
          </div>
          <div v-else-if="debugLoading" class="bg-base border border-edge rounded px-3 py-2">
            <span class="text-xs text-content-muted">Loading system prompt...</span>
          </div>

          <!-- Chat Items -->
          <div
            v-for="item in topLevelItems"
            :key="item.id"
            :data-item-id="item.id"
            class="bg-base border border-edge rounded p-3 relative transition-all"
            :class="{ 'border-purple-500': focusedItemId === item.id }"
          >
            <div class="absolute top-2 right-2 flex gap-1">
              <!-- View LLM Trace (for items with associated traces) -->
              <button
                v-if="hasTraceForItem(item)"
                @click="openTraceForItem(item)"
                class="p-1 rounded debug-btn debug-btn-purple"
                title="View LLM trace"
              >
                <ChartBarSquareIcon class="w-4 h-4" />
              </button>
              <!-- Replay (user messages only) -->
              <button
                v-if="item.item_type === 'user_message'"
                @click="replayFromHere(item)"
                class="p-1 rounded debug-btn debug-btn-emerald"
                title="Delete from here and resend this message"
              >
                <!-- Custom replay icon: play with circular arrow -->
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12a7.5 7.5 0 0 1 12.803-5.303" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12a7.5 7.5 0 0 1-12.803 5.303" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 4.5l.803 2.197L19.5 7.5" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M10 8.5v7l5.5-3.5-5.5-3.5z" />
                </svg>
              </button>
              <!-- Copy JSON from here -->
              <button
                @click="copyJsonFromHere(item.id)"
                class="p-1 rounded debug-btn debug-btn-amber flex items-center gap-0.5"
                title="Copy JSON from here to clipboard"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
                </svg>
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 5.25 7.5 7.5 7.5-7.5m-15 6 7.5 7.5 7.5-7.5" />
                </svg>
              </button>
              <!-- Delete from here -->
              <button
                @click="deleteFromHere(item.id)"
                class="p-1 rounded debug-btn debug-btn-red flex items-center gap-0.5"
                title="Delete this and all below"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 5.25 7.5 7.5 7.5-7.5m-15 6 7.5 7.5 7.5-7.5" />
                </svg>
              </button>
              <!-- Delete single -->
              <button
                @click="deleteItem(item.id)"
                class="p-1 rounded debug-btn debug-btn-red"
                title="Delete item"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
              </button>
            </div>
            <div class="text-xs text-content-muted mb-1">
              ID: {{ item.id }} | Type: {{ item.item_type }} | Created: {{ new Date(item.created_at).toLocaleString() }}
            </div>
            <pre class="text-xs text-content-secondary overflow-x-auto whitespace-pre-wrap json-highlighted" v-html="formatJsonWithHighlighting(item)"></pre>
            <!-- Subagent child items (delegate deep-dive in raw view) -->
            <details v-if="item.item_type === 'tool_call' && item.tool_name === 'delegate' && getChildItems(item.id).length > 0" class="mt-2 border-t border-edge pt-2">
              <summary class="text-xs text-purple-400 cursor-pointer hover:text-purple-300 flex items-center gap-2">
                <span>Subagent activity ({{ getChildItems(item.id).length }} items)</span>
                <button
                  @click.stop.prevent="copyChildItems(item.id)"
                  class="p-0.5 rounded hover:bg-purple-500/20 text-purple-400 hover:text-purple-300"
                  title="Copy subagent trace to clipboard"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
                  </svg>
                </button>
              </summary>
              <div class="mt-2 ml-4 space-y-2 border-l-2 border-purple-500/30 pl-3">
                <div
                  v-for="child in getChildItems(item.id)"
                  :key="child.id"
                  class="bg-surface border border-edge rounded p-2"
                >
                  <div class="text-xs text-content-muted mb-1">
                    ID: {{ child.id }} | Type: {{ child.item_type }} | Created: {{ new Date(child.created_at).toLocaleString() }}
                  </div>
                  <pre class="text-xs text-content-secondary overflow-x-auto whitespace-pre-wrap json-highlighted" v-html="formatJsonWithHighlighting(child)"></pre>
                </div>
              </div>
            </details>
          </div>

          <!-- Conversation Summary -->
          <div v-if="debugMessages" class="bg-surface border border-edge rounded px-3 py-2 mt-4 space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-xs text-content-tertiary">{{ getContextSummary() }}</span>
              <button @click="fetchDebugMessages" class="text-[10px] text-content-muted hover:text-content-secondary">refresh</button>
            </div>
            <!-- Token usage from last LLM call -->
            <div v-if="llmUsage" class="flex items-center gap-3">
              <div class="flex-1 h-1.5 bg-surface-raised rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-300"
                  :class="tokenUsagePercent > 80 ? 'bg-red-500' : tokenUsagePercent > 50 ? 'bg-amber-500' : 'bg-emerald-500'"
                  :style="{ width: tokenUsagePercent + '%' }"
                />
              </div>
              <span class="text-[10px] text-content-muted whitespace-nowrap">
                {{ formatTokenCount(llmUsage.prompt_tokens) }} / {{ formatTokenCount(contextLimit) }} tokens
                <span v-if="llmUsage.completion_tokens">(+{{ formatTokenCount(llmUsage.completion_tokens) }} out)</span>
              </span>
            </div>
          </div>
        </div>

        <!-- Normal Chat View -->
        <div v-else class="space-y-2">
          <div
            v-for="item in topLevelItems"
            :key="item.id"
            class="chat-item"
          >
          <!-- Activity Group: skip non-first items (they render as part of the group) -->
          <template v-if="getActivityGroup(item.id) && !isFirstInActivityGroup(item.id)"></template>

          <!-- Activity Group: render collapsed/expanded group at first item position -->
          <!-- Activity Group: hide if all tools are infrastructure and not running -->
          <template v-else-if="isFirstInActivityGroup(item.id) && !getActivityGroupSummary(getActivityGroup(item.id)).isRunning && getActivityGroupSummary(getActivityGroup(item.id)).toolNames.length === 0"></template>

          <div v-else-if="isFirstInActivityGroup(item.id)" class="flex justify-start">
            <div class="activity-group select-none" :class="{ 'activity-group--running': getActivityGroupSummary(getActivityGroup(item.id)).isRunning }">
              <!-- Collapsed summary line -->
              <div
                class="activity-summary"
                @click="toggleActivityGroup(getActivityGroup(item.id).id)"
              >
                <ChevronRightIcon
                  class="activity-chevron"
                  :class="{ 'rotate-90': isActivityGroupExpanded(getActivityGroup(item.id).id) }"
                />
                <template v-if="getActivityGroupSummary(getActivityGroup(item.id)).isRunning">
                  <span class="activity-pulse"></span>
                </template>
                <span class="activity-tool-list">
                  <template v-if="getActivityGroupSummary(getActivityGroup(item.id)).toolNames.length > 0">
                    <span class="activity-tool-name">{{ getActivityGroupSummary(getActivityGroup(item.id)).toolNames[getActivityGroupSummary(getActivityGroup(item.id)).toolNames.length - 1] }}</span>
                  </template>
                  <span v-else-if="!getActivityGroupSummary(getActivityGroup(item.id)).hasRunningThinking" class="activity-tool-name">Working</span>
                </span>
                <span v-if="getActivityGroupSummary(getActivityGroup(item.id)).hasRunningThinking" class="activity-thinking" :class="{ 'activity-thinking--solo': getActivityGroupSummary(getActivityGroup(item.id)).toolNames.length === 0 }">
                    <span class="thinking-dots">thinking</span>
                </span>
                <span v-if="getActivityGroupSummary(getActivityGroup(item.id)).hasFailed && !getActivityGroupSummary(getActivityGroup(item.id)).isRunning && isLastActivityGroup(getActivityGroup(item.id))" class="activity-failed-badge">failed</span>
              </div>

              <!-- Expanded timeline -->
              <div v-if="isActivityGroupExpanded(getActivityGroup(item.id).id)" class="activity-timeline">
                <div
                  v-for="(actItem, stepIdx) in getVisibleActivityItems(getActivityGroup(item.id))"
                  :key="actItem.id"
                  class="activity-step"
                  :class="{ 'activity-step--last': stepIdx === getVisibleActivityItems(getActivityGroup(item.id)).length - 1 }"
                >
                  <div class="activity-step-connector">
                    <div class="activity-step-branch"></div>
                  </div>
                  <!-- Thinking step (expandable when content available) -->
                  <template v-if="actItem.item_type === 'assistant_message' && hasThinking(actItem)">
                    <div v-if="isThinkingInterrupted(actItem)" class="activity-step-summary" style="cursor: default;">
                      <span class="text-content-muted">Interrupted</span>
                    </div>
                    <details v-else-if="getThinkingContent(actItem)" class="activity-details flex-1 min-w-0">
                      <summary class="activity-step-summary">
                        <template v-if="isThinkingInProgress(actItem)">
                          <span class="thinking-dots text-content-muted">Thinking</span>
                        </template>
                        <template v-else>
                          <span class="text-content-muted">Thought for {{ getThinkingDuration(actItem) }}</span>
                        </template>
                      </summary>
                      <div class="activity-step-content">
                        <div class="prose prose-sm max-w-none text-content-secondary" v-html="renderMarkdown(getThinkingContent(actItem))"></div>
                      </div>
                    </details>
                    <div v-else-if="isThinkingInProgress(actItem)" class="activity-step-summary" style="cursor: default;">
                      <span class="thinking-dots text-content-muted">Thinking</span>
                    </div>
                  </template>

                  <!-- Tool call step: browse_web gets a flat row with clickable link -->
                  <template v-else-if="actItem.item_type === 'tool_call' && actItem.tool_name === 'browse_web'">
                    <div class="activity-step-summary" style="cursor: default;">
                      <span class="activity-step-name">{{ getToolCallDisplayName(actItem) }}</span>
                      <a
                        v-if="devModeRef && actItem.tool_args?.action === 'fetch' && actItem.tool_args?.url"
                        :href="actItem.tool_args.url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="activity-step-preview hover:underline cursor-pointer"
                      >{{ actItem.tool_args.url }}</a>
                      <span v-else-if="devModeRef && getToolCallPreview(actItem)" class="activity-step-preview">{{ getToolCallPreview(actItem) }}</span>
                      <span v-if="getToolCallStatus(actItem) === 'failed'" class="activity-failed-badge">failed</span>
                      <span v-if="getToolCallStatus(actItem) === 'running'" class="activity-running-badge">running</span>
                    </div>

                  <!-- Tool call step: delegate gets nested subagent activity -->
                  </template>
                  <template v-else-if="actItem.item_type === 'tool_call' && actItem.tool_name === 'delegate'">
                    <details class="activity-details flex-1 min-w-0" :open="isDelegateExpanded(actItem.id) || undefined" @toggle="onDelegateToggle(actItem.id, $event)">
                      <summary class="activity-step-summary">
                        <span class="activity-step-name">{{ getToolCallDisplayName(actItem) }}</span>
                        <span v-if="getDelegateActivitySummary(actItem.id).hasRunningThinking" class="activity-thinking">
                          <span class="thinking-dots">thinking</span>
                        </span>
                        <span
                          v-if="getToolCallStatus(actItem) === 'failed'"
                          class="activity-failed-badge"
                        >failed</span>
                        <span
                          v-if="getToolCallStatus(actItem) === 'running' && !getDelegateActivitySummary(actItem.id).isRunning"
                          class="activity-running-badge"
                        >running</span>
                        <span
                          v-if="getDelegateActivitySummary(actItem.id).isRunning"
                          class="activity-running-badge"
                        >running</span>
                      </summary>
                      <!-- Nested subagent activity — continues the tree structure -->
                      <div v-if="getDelegateActivityItems(actItem.id).length > 0" class="activity-timeline">
                        <div
                          v-for="(childItem, childIdx) in getDelegateActivityItems(actItem.id)"
                          :key="childItem.id"
                          class="activity-step"
                          :class="{ 'activity-step--last': childIdx === getDelegateActivityItems(actItem.id).length - 1 }"
                        >
                          <div class="activity-step-connector">
                            <div class="activity-step-branch"></div>
                          </div>
                          <!-- Thinking step -->
                          <template v-if="childItem.item_type === 'assistant_message' && hasThinking(childItem)">
                            <div v-if="isThinkingInterrupted(childItem)" class="activity-step-summary" style="cursor: default;">
                              <span class="text-content-muted">Interrupted</span>
                            </div>
                            <details v-else-if="getThinkingContent(childItem)" class="activity-details flex-1 min-w-0">
                              <summary class="activity-step-summary">
                                <template v-if="isThinkingInProgress(childItem)">
                                  <span class="thinking-dots text-content-muted">Thinking</span>
                                </template>
                                <template v-else>
                                  <span class="text-content-muted">Thought for {{ getThinkingDuration(childItem) }}</span>
                                </template>
                              </summary>
                              <div class="activity-step-content">
                                <div class="prose prose-sm max-w-none text-content-secondary" v-html="renderMarkdown(getThinkingContent(childItem))"></div>
                              </div>
                            </details>
                            <div v-else-if="isThinkingInProgress(childItem)" class="activity-step-summary" style="cursor: default;">
                              <span class="thinking-dots text-content-muted">Thinking</span>
                            </div>
                          </template>
                          <!-- Tool call step — expandable like parent tool calls -->
                          <template v-else-if="childItem.item_type === 'tool_call'">
                            <details class="activity-details flex-1 min-w-0">
                              <summary class="activity-step-summary">
                                <span class="activity-step-name">{{ getToolCallDisplayName(childItem) }}</span>
                                <span v-if="devModeRef && getToolCallPreview(childItem)" class="activity-step-preview">{{ getToolCallPreview(childItem) }}</span>
                                <span v-if="getDelegateChildToolStatus(childItem, getChildItems(actItem.id)) === 'failed'" class="activity-failed-badge">failed</span>
                                <span v-if="getDelegateChildToolStatus(childItem, getChildItems(actItem.id)) === 'running'" class="activity-running-badge">running</span>
                              </summary>
                              <div v-if="getDelegateChildToolDetails(childItem) || getDelegateChildToolStatus(childItem, getChildItems(actItem.id)) === 'failed' || (devModeRef && getToolCallResultData(childItem))" class="activity-step-content">
                                <div v-if="getDelegateChildToolStatus(childItem, getChildItems(actItem.id)) === 'failed'" class="text-sm text-red-400/80 mb-1">
                                  {{ getDelegateChildToolError(childItem) }}
                                </div>
                                <template v-if="getDelegateChildToolDetails(childItem)">
                                  <div v-if="getToolCallDetailKind(childItem) === 'code'" class="activity-code-block">
                                    <pre class="text-sm leading-6"><code v-html="renderHighlightedCode(getDelegateChildToolDetails(childItem), getToolCallLanguage(childItem))" /></pre>
                                  </div>
                                  <div v-else-if="getToolCallDetailKind(childItem) === 'json' && devModeRef" class="activity-code-block">
                                    <pre class="text-xs text-content-secondary whitespace-pre-wrap json-highlighted" v-html="formatToolCallJson(childItem)"></pre>
                                  </div>
                                  <div v-else-if="getToolCallDetailKind(childItem) !== 'json'" class="text-sm text-content-secondary whitespace-pre-wrap break-words">{{ getDelegateChildToolDetails(childItem) }}</div>
                                </template>
                                <div v-if="devModeRef && getToolCallResultData(childItem)" class="activity-code-block mt-1">
                                  <div class="text-[10px] text-content-muted uppercase tracking-wider mb-0.5">Response</div>
                                  <pre class="text-xs text-content-secondary whitespace-pre-wrap json-highlighted" v-html="formatToolResultJson(childItem)"></pre>
                                </div>
                              </div>
                            </details>
                          </template>
                        </div>
                      </div>
                    </details>
                  </template>

                  <!-- Tool call step: expandable only when there is visible content -->
                  <template v-else-if="actItem.item_type === 'tool_call'">
                    <details v-if="toolCallHasExpandableContent(actItem)" class="activity-details flex-1 min-w-0">
                      <summary class="activity-step-summary">
                        <span class="activity-step-name">{{ getToolCallDisplayName(actItem) }}</span>
                        <span v-if="devModeRef && getToolCallPreview(actItem)" class="activity-step-preview">{{ getToolCallPreview(actItem) }}</span>
                        <span
                          v-if="getToolCallStatus(actItem) === 'failed'"
                          class="activity-failed-badge"
                        >failed</span>
                        <span
                          v-if="getToolCallStatus(actItem) === 'running'"
                          class="activity-running-badge"
                        >running</span>
                      </summary>
                      <div v-if="getToolCallDetails(actItem) || getToolCallStatus(actItem) === 'failed' || (devModeRef && getToolCallResultData(actItem))" class="activity-step-content">
                        <div v-if="getToolCallStatus(actItem) === 'failed'" class="text-sm text-red-400/80 mb-1">
                          {{ getToolCallErrorMessage(actItem) }}
                        </div>
                        <template v-if="getToolCallDetails(actItem)">
                          <div v-if="getToolCallDetailKind(actItem) === 'code'" class="activity-code-block">
                            <pre class="text-sm leading-6"><code v-html="renderHighlightedCode(getToolCallDetails(actItem), getToolCallLanguage(actItem))" /></pre>
                          </div>
                          <div v-else-if="getToolCallDetailKind(actItem) === 'json' && devModeRef" class="activity-code-block">
                            <pre class="text-xs text-content-secondary whitespace-pre-wrap json-highlighted" v-html="formatToolCallJson(actItem)"></pre>
                          </div>
                          <div v-else-if="getToolCallDetailKind(actItem) !== 'json'" class="text-sm text-content-secondary whitespace-pre-wrap break-words">{{ getToolCallDetails(actItem) }}</div>
                        </template>
                        <div v-if="devModeRef && getToolCallResultData(actItem)" class="activity-code-block mt-1">
                          <div class="text-[10px] text-content-muted uppercase tracking-wider mb-0.5">Response</div>
                          <pre class="text-xs text-content-secondary whitespace-pre-wrap json-highlighted" v-html="formatToolResultJson(actItem)"></pre>
                        </div>
                      </div>
                    </details>
                    <div v-else class="activity-step-summary activity-details flex-1 min-w-0" style="cursor: default; list-style: none;">
                      <span class="activity-step-name">{{ getToolCallDisplayName(actItem) }}</span>
                      <span v-if="devModeRef && getToolCallPreview(actItem)" class="activity-step-preview">{{ getToolCallPreview(actItem) }}</span>
                      <span
                        v-if="getToolCallStatus(actItem) === 'running'"
                        class="activity-running-badge"
                      >running</span>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- User Message: right-aligned, max 50% width (expands when editing) -->
          <!-- Stop event: subtle centered "Interrupted" indicator -->
          <div v-else-if="item.item_type === 'user_message' && isStopEvent(item)" class="flex justify-center py-1">
            <span class="text-xs text-content-muted italic">Interrupted</span>
          </div>

          <div v-else-if="item.item_type === 'user_message'" class="flex justify-end">
            <ChatItemWrapper
              :item-id="item.id"
              align="right"
              :class="editingItemId === item.id ? 'max-w-[80%]' : 'max-w-[50%]'"
              :show-actions="editingItemId !== item.id"
              :show-edit="!!item.message_text"
              :show-replay="!!item.message_text"
              @edit="startEditing(item)"
              @replay="replayFromHere(item)"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="bg-blue-600 text-white rounded-lg px-4 py-2">
                <!-- Attachments -->
                <div v-if="getMessageAttachments(item).length > 0" class="flex gap-2 mb-2">
                  <div
                    v-for="(attachment, idx) in getMessageAttachments(item)"
                    :key="idx"
                    class="w-16 h-16 rounded overflow-hidden flex-shrink-0"
                  >
                    <!-- Deleted asset placeholder (deleted flag from API or broken during session) -->
                    <div
                      v-if="attachment.deleted || (attachment.media_id && isMediaBroken(attachment.media_id))"
                      class="w-full h-full bg-surface flex items-center justify-center"
                      title="Asset deleted"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-6 h-6 text-content-muted">
                        <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
                      </svg>
                    </div>
                    <!-- Library media (has media_id) — click opens generation/image details -->
                    <MediaImage
                      v-else-if="attachment.media_id"
                      :mediaId="attachment.media_id"
                      :thumbnail="true"
                      :thumbnailSize="128"
                      containerClass="w-full h-full cursor-pointer"
                      @click="openMediaDetails(attachment.media_id)"
                      @error="handleMediaLoadError(attachment.media_id)"
                    />
                    <!-- Reference file (path only) -->
                    <AppImage
                      v-else
                      :src="getAttachmentThumbnail(attachment)"
                      containerClass="w-full h-full"
                    />
                  </div>
                </div>
                <!-- Flow reference chips (parsed from the message header so
                     the raw markdown transport never shows up in the bubble) -->
                <div
                  v-if="getMessageRefs(item).length > 0"
                  class="flex flex-wrap gap-1 mb-2"
                >
                  <FlowRefChip
                    v-for="r in getMessageRefs(item)"
                    :key="r.refKey"
                    :label="r.label"
                    :breadcrumb="r.breadcrumb"
                    variant="bubble"
                  />
                </div>
                <!-- Message text (or inline editor) -->
                <div v-if="getMessageBodyText(item)">
                  <!-- Inline editor when editing this item -->
                  <textarea v-no-autocorrect
                    v-if="editingItemId === item.id"
                    data-edit-input
                    ref="editTextarea"
                    v-model="editingText"
                    @keydown="handleEditKeydown($event, item)"
                    @blur="cancelEditing"
                    @input="autoResizeEditTextarea"
                    :style="{ minWidth: editingMinSize.width + 'px', minHeight: editingMinSize.height + 'px' }"
                    class="w-full bg-blue-700 text-white rounded px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-edge-strong"
                  ></textarea>
                  <!-- Normal text display -->
                  <span v-else class="whitespace-pre-wrap break-words">{{ getMessageBodyText(item) }}</span>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Assistant Message: left-aligned, can expand -->
          <div v-else-if="item.item_type === 'assistant_message' && (hasThinking(item) || getDisplayText(item))" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              :show-thumbs="true"
              :thumb-agent-context="chat?.flow_id ? 'flow' : 'main'"
              :thumb-package-source="{ type: 'chat', chatId }"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="space-y-1.5">
                <!-- Thinking indicator (hidden when absorbed by preceding activity group) -->
                <template v-if="hasThinking(item) && !itemsFollowingActivityGroup.has(item.id)">
                  <div v-if="isThinkingInterrupted(item)" class="activity-summary select-none" style="display: inline-flex; cursor: default;">
                    <span class="text-content-muted">Interrupted</span>
                  </div>
                  <details v-else-if="getThinkingContent(item)" class="activity-details inline-block select-none">
                    <summary class="activity-summary" style="display: inline-flex;">
                      <ChevronRightIcon class="activity-chevron" />
                      <template v-if="isThinkingInProgress(item)">
                        <span class="activity-pulse"></span>
                        <span class="thinking-dots">thinking</span>
                      </template>
                      <template v-else>
                        <span>Thought for {{ getThinkingDuration(item) }}</span>
                      </template>
                    </summary>
                    <div class="activity-step-content mt-1.5">
                      <div class="prose prose-sm max-w-none text-content-secondary" v-html="renderMarkdown(getThinkingContent(item))"></div>
                    </div>
                  </details>
                  <div v-else-if="isThinkingInProgress(item)" class="activity-summary select-none" style="display: inline-flex; cursor: default;">
                    <span class="activity-pulse"></span>
                    <span class="thinking-dots">thinking</span>
                  </div>
                </template>
                <div
                  v-if="getDisplayText(item)"
                  class="bg-surface text-content rounded-lg px-4 py-2 prose prose-sm max-w-none"
                >
                  <template v-for="(seg, segIdx) in parseMarkdownSegments(getDisplayText(item))" :key="segIdx">
                    <span v-if="seg.type === 'html'" v-html="seg.content"></span>
                    <MediaImage
                      v-else-if="seg.type === 'media'"
                      :media-id="seg.mediaId"
                      :thumbnail="true"
                      :thumbnail-size="512"
                      container-class="w-[320px] h-[200px] rounded-lg overflow-hidden cursor-pointer my-2"
                      img-class="w-full h-full object-cover"
                      @click="openSlideshow(seg.mediaId, 0)"
                    />
                  </template>
                </div>
                <!-- Dev mode: per-item token usage -->
                <div v-if="devModeRef && item.item_metadata?.llm_usage" class="text-[10px] text-content-muted font-mono px-1 select-none">
                  {{ item.item_metadata.llm_usage.model }} · {{ formatTokenCount(item.item_metadata.llm_usage.prompt_tokens) }} in / {{ formatTokenCount(item.item_metadata.llm_usage.completion_tokens) }} out<template v-if="item.item_metadata.llm_usage.reasoning_tokens"> / {{ formatTokenCount(item.item_metadata.llm_usage.reasoning_tokens) }} reasoning</template><template v-if="item.item_metadata.llm_usage.cache_read_input_tokens"> · <span class="text-teal-500">cache {{ formatTokenCount(item.item_metadata.llm_usage.cache_read_input_tokens) }} hit<template v-if="item.item_metadata.llm_usage.cache_creation_input_tokens"> / {{ formatTokenCount(item.item_metadata.llm_usage.cache_creation_input_tokens) }} write</template></span></template><template v-if="item.item_metadata.llm_usage.tokens_per_second"> · {{ item.item_metadata.llm_usage.tokens_per_second.toFixed(1) }} t/s</template>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Error: left-aligned -->
          <!-- LLM not configured (OOBE setup prompt) -->
          <div v-else-if="item.item_type === 'error' && isLLMSetupError(item)" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="rounded-xl max-w-xs overflow-hidden p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
                <div class="bg-surface-elevated rounded-lg overflow-hidden">
                  <div class="flex items-center gap-2 px-3.5 py-2 border-b border-edge-subtle">
                    <div class="p-1 rounded-md bg-teal-600/15 flex-shrink-0">
                      <SparklesIcon class="w-3.5 h-3.5 text-teal-400" />
                    </div>
                    <span class="text-sm font-medium stimma-cloud-text">Almost There</span>
                  </div>
                  <div class="px-3.5 py-3 space-y-3">
                    <p class="text-sm text-content-secondary text-center">Connect Stimma Cloud to start chatting.</p>
                    <button
                      @click="handleCloudSignIn"
                      :disabled="cloudSigningIn"
                      class="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 disabled:opacity-60 transition-all text-white text-sm font-medium w-full"
                    >
                      <SparklesIcon class="w-4 h-4 flex-shrink-0" />
                      {{ cloudSigningIn ? 'Connecting...' : 'Get Started with Stimma Cloud' }}
                    </button>
                    <button
                      @click="openAISettings"
                      class="block w-full text-center text-xs text-content-muted hover:text-content-secondary transition-colors"
                    >Or configure a local LLM</button>
                  </div>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Subscription required (signed in but free tier) -->
          <div v-else-if="item.item_type === 'error' && item.item_metadata?.error_type === 'subscription_required'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="rounded-xl max-w-xs overflow-hidden p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
                <div class="bg-surface-elevated rounded-lg overflow-hidden">
                  <div class="flex items-center gap-2 px-3.5 py-2 border-b border-edge-subtle">
                    <div class="p-1 rounded-md bg-teal-600/15 flex-shrink-0">
                      <SparklesIcon class="w-3.5 h-3.5 text-teal-400" />
                    </div>
                    <span class="text-sm font-medium stimma-cloud-text">Subscription Required</span>
                  </div>
                  <div class="px-3.5 py-3 space-y-3">
                    <p class="text-sm text-content-secondary text-center">Subscribe to Stimma Cloud to start chatting.</p>
                    <a
                      href="#"
                      @click.prevent="openPricingPage"
                      class="flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 transition-all text-white text-sm font-medium w-full"
                    >
                      See Plans
                    </a>
                    <button
                      @click="refreshAccountAndRetry"
                      :disabled="accountRefreshing"
                      class="block w-full text-center text-xs text-content-muted hover:text-content-secondary transition-colors"
                    >{{ accountRefreshing ? 'Checking...' : 'I just subscribed' }}</button>
                    <button
                      @click="openAISettings"
                      class="block w-full text-center text-xs text-content-muted hover:text-content-secondary transition-colors"
                    >Or use your own endpoint</button>
                    <ChatErrorDisclosure :raw="getRawErrorDetails(item)" />
                  </div>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Quota exceeded error (Stimma Cloud) -->
          <div v-else-if="item.item_type === 'error' && item.item_metadata?.error_type === 'quota_exceeded'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="rounded-xl max-w-lg overflow-hidden p-[1px] bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40">
                <div class="bg-surface-elevated rounded-lg overflow-hidden">
                  <div class="flex items-center gap-2 px-3.5 py-2 border-b border-edge-subtle">
                    <div class="p-1 rounded-md bg-teal-600/15 flex-shrink-0">
                      <ExclamationTriangleIcon class="w-3.5 h-3.5 text-teal-400" />
                    </div>
                    <span class="text-sm font-medium stimma-cloud-text">Usage Limit Reached</span>
                  </div>
                  <div class="px-3.5 py-3 space-y-3">
                    <p class="text-sm text-content-secondary">{{ item.item_metadata?.error_summary || item.message_text }}</p>
                    <div class="space-y-2">
                      <!-- Session quota -->
                      <div v-if="item.item_metadata?.session" class="space-y-1">
                        <div class="flex items-center justify-between text-xs">
                          <span class="text-content-muted">Session</span>
                          <div class="flex items-center gap-1 text-content-muted">
                            <ClockIcon class="w-3 h-3" />
                            <span>Resets in {{ formatQuotaReset(item.item_metadata.session.resetsAt) }}</span>
                          </div>
                        </div>
                        <div class="h-1.5 rounded-full bg-surface-raised overflow-hidden">
                          <div
                            class="h-full rounded-full bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 transition-all"
                            :style="{ width: Math.min(item.item_metadata.session.percentUsed, 100) + '%' }"
                          />
                        </div>
                      </div>
                      <!-- Weekly quota -->
                      <div v-if="item.item_metadata?.weekly" class="space-y-1">
                        <div class="flex items-center justify-between text-xs">
                          <span class="text-content-muted">Weekly</span>
                          <div class="flex items-center gap-1 text-content-muted">
                            <ClockIcon class="w-3 h-3" />
                            <span>Resets in {{ formatQuotaReset(item.item_metadata.weekly.resetsAt) }}</span>
                          </div>
                        </div>
                        <div class="h-1.5 rounded-full bg-surface-raised overflow-hidden">
                          <div
                            class="h-full rounded-full bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 transition-all"
                            :style="{ width: Math.min(item.item_metadata.weekly.percentUsed, 100) + '%' }"
                          />
                        </div>
                      </div>
                    </div>
                    <a
                      href="#"
                      @click.prevent="openCloudDashboard"
                      class="inline-flex items-center gap-1 text-xs stimma-cloud-text hover:opacity-80 transition-opacity mt-1"
                    >Manage Account</a>
                    <ChatErrorDisclosure :raw="getRawErrorDetails(item)" />
                  </div>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Content filtered error -->
          <div v-else-if="item.item_type === 'error' && item.item_metadata?.error_type === 'content_filtered'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="rounded-xl max-w-lg overflow-hidden p-[1px] bg-gradient-to-r from-amber-500/40 via-orange-500/40 to-red-500/40">
                <div class="bg-surface-elevated rounded-lg overflow-hidden">
                  <div class="flex items-center gap-2 px-3.5 py-2 border-b border-edge-subtle">
                    <div class="p-1 rounded-md bg-amber-500/15 flex-shrink-0">
                      <ShieldExclamationIcon class="w-3.5 h-3.5 text-amber-400" />
                    </div>
                    <span class="text-sm font-medium text-amber-300">Content Guidelines</span>
                  </div>
                  <div class="px-3.5 py-3 space-y-3">
                    <p class="text-sm text-content-secondary">{{ item.item_metadata?.error_summary || item.message_text }}</p>
                    <ChatErrorDisclosure :raw="getRawErrorDetails(item)" />
                  </div>
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Generic error -->
          <div v-else-if="item.item_type === 'error'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="bg-surface/80 rounded-xl border border-red-500/30 max-w-lg overflow-hidden">
                <div class="flex items-center gap-2 px-3.5 py-2 border-b border-red-500/15 bg-red-500/[0.06]">
                  <div class="p-1 rounded-md bg-red-500/15 flex-shrink-0">
                    <ExclamationTriangleIcon class="w-3.5 h-3.5 text-red-400" />
                  </div>
                  <span class="text-sm font-medium text-red-400">Error</span>
                </div>
                <div class="px-3.5 py-2.5 space-y-3">
                  <div class="text-sm text-content-secondary">{{ GENERIC_CHAT_ERROR_MESSAGE }}</div>
                  <div v-if="isLastChatItem(item)">
                    <button
                      type="button"
                      @click="retryAfterError"
                      :disabled="agentRunning || agentPlanning || sending"
                      class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/15 hover:text-red-200 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium transition-colors"
                    >
                      <ArrowPathIcon class="w-3.5 h-3.5" />
                      Try again
                    </button>
                  </div>
                  <ChatErrorDisclosure :raw="getRawErrorDetails(item)" />
                </div>
              </div>
            </ChatItemWrapper>
          </div>

          <!-- System: left-aligned, can expand -->
          <div v-else-if="item.item_type === 'system'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <!-- Plan visualization if this is a plan item -->
              <div
                v-if="hasPlanData(item)"
                class="bg-surface/80 rounded-xl border border-edge-subtle overflow-hidden transition-all duration-200"
                :class="isPlanExpanded(item.id) ? 'min-w-[520px]' : ''"
              >
                <!-- Plan header -->
                <div
                  class="flex items-center justify-between px-3.5 py-2 border-b border-blue-500/15 bg-blue-500/[0.06] cursor-pointer select-none"
                  @click="togglePlanExpanded(item.id)"
                >
                  <div class="flex items-center gap-2">
                    <div class="p-1 rounded-md bg-blue-500/15 flex-shrink-0">
                      <ListBulletIcon class="w-3.5 h-3.5 text-blue-500" />
                    </div>
                    <span class="text-sm font-medium text-blue-400">Plan</span>
                    <ChevronRightIcon
                      class="w-3.5 h-3.5 text-content-muted transition-transform duration-200 flex-shrink-0"
                      :class="{ 'rotate-90': isPlanExpanded(item.id) }"
                    />
                  </div>
                  <button
                    v-if="isPlanExpanded(item.id)"
                    @click.stop="toggleRawPlan(item.id)"
                    class="text-[11px] uppercase tracking-wide transition-colors select-none"
                    :class="rawPlanItemIds.has(item.id) ? 'text-blue-400' : 'text-content-muted hover:text-content-secondary'"
                  >Raw</button>
                </div>
                <!-- Plan body (collapsible) -->
                <div v-show="isPlanExpanded(item.id)" class="px-3.5 py-3">
                  <!-- Raw JSON view -->
                  <pre v-if="rawPlanItemIds.has(item.id)" class="text-xs whitespace-pre-wrap break-words font-mono text-content-muted max-h-96 overflow-y-auto custom-scrollbar">{{ JSON.stringify(getPlanData(item), null, 2) }}</pre>
                  <!-- Visual plan -->
                  <PlanVisualization
                    v-else
                    :key="`plan-${item.id}-${nodeStatesKey}`"
                    :plan="getPlanData(item)"
                    :execution-state="getMergedExecutionState(item)"
                  />
                </div>
              </div>
              <!-- Notepad display -->
              <NotepadDisplay
                v-else-if="hasNotepadData(item)"
                :tasks="parseNotepadData(item).tasks"
                :scratchpad="parseNotepadData(item).scratchpad"
              />
              <!-- Regular system message -->
              <div v-else class="bg-surface text-content-tertiary rounded-lg px-4 py-2 text-sm">
                {{ item.message_text }}
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Tool Call (fallback — most are absorbed into activity groups) -->
          <div v-else-if="item.item_type === 'tool_call'" class="flex justify-start">
            <div class="activity-group">
              <details class="activity-details inline-block">
                <summary class="activity-summary" style="display: inline-flex;">
                  <ChevronRightIcon class="activity-chevron" />
                  <span v-if="getToolCallStatus(item) === 'running'" class="activity-pulse"></span>
                  <span class="activity-tool-name">{{ getToolCallDisplayName(item) }}</span>
                  <span v-if="getToolCallStatus(item) === 'failed'" class="activity-failed-badge">failed</span>
                </summary>
                <div v-if="getToolCallDetails(item)" class="activity-step-content mt-1">
                  <div v-if="getToolCallDetailKind(item) === 'code'" class="activity-code-block">
                    <pre class="text-sm leading-6"><code v-html="renderHighlightedCode(getToolCallDetails(item), getToolCallLanguage(item))" /></pre>
                  </div>
                  <div v-else-if="getToolCallDetailKind(item) === 'json'" class="activity-code-block">
                    <pre class="text-xs text-content-secondary whitespace-pre-wrap json-highlighted" v-html="formatToolCallJson(item)"></pre>
                  </div>
                  <div v-else class="text-sm text-content-secondary whitespace-pre-wrap break-words">{{ getToolCallDetails(item) }}</div>
                </div>
              </details>
            </div>
          </div>

          <!-- Tool Result - show errors only when NOT inside an activity group -->
          <div
            v-else-if="item.item_type === 'tool_result' && item.tool_result?.error && !isToolResultInActivityGroup(item)"
            class="flex justify-start"
          >
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="bg-surface/80 rounded-xl border border-red-500/30 overflow-hidden">
                <div class="flex items-center gap-2 px-3.5 py-2 border-b border-red-500/15 bg-red-500/[0.06]">
                  <div class="p-1 rounded-md bg-red-500/15 flex-shrink-0">
                    <ExclamationTriangleIcon class="w-3.5 h-3.5 text-red-400" />
                  </div>
                  <span class="text-sm font-medium text-red-400">Tool error</span>
                </div>
                <div class="px-3.5 py-2.5 text-sm text-content-secondary">
                  {{ item.tool_result.description || item.tool_result.error }}
                </div>
              </div>
            </ChatItemWrapper>
          </div>
          <template v-else-if="item.item_type === 'tool_result'"></template>

          <!-- Media Display: left-aligned, expands as needed -->
          <div v-else-if="item.item_type === 'media_display'" class="flex justify-start">
            <ChatItemWrapper
              class="w-full"
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <MediaDisplay
                :display-data="parseMediaDisplayData(item)"
                :chat-item-id="item.id"
                @view-image="openSlideshow"
                @show-job-info="showJobInfoById"
              />
            </ChatItemWrapper>
          </div>

          <!-- Progress Display: progress bar + thumbnail previews -->
          <div v-else-if="item.item_type === 'progress_display'" class="flex justify-start w-1/2 min-w-[280px]">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <ProgressDisplay
                :display-data="parseProgressDisplayData(item)"
                @view-image="openSlideshow"
              />
            </ChatItemWrapper>
          </div>

          <!-- Grid Generation: displays grid progress and results -->
          <div v-else-if="item.item_type === 'grid_generation'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <GridGenerationDisplay
                :display-data="parseGridGenerationData(item)"
                :chat-item-id="item.id"
                @view-image="openSlideshow"
                @view-grid="openSlideshow"
              />
            </ChatItemWrapper>
          </div>

          <!-- Scored Results: shows images with their scores -->
          <div v-else-if="item.item_type === 'scored_results'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <ScoredResultsDisplay
                :scored-data="parseScoredResultsData(item)"
                @view-image="openSlideshow"
              />
            </ChatItemWrapper>
          </div>

          <!-- Analysis Result: left-aligned, for text analysis output -->
          <div v-else-if="item.item_type === 'analysis_result'" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <AnalysisResult
                :analysis-data="parseAnalysisData(item)"
                @view-image="openSlideshow"
              />
            </ChatItemWrapper>
          </div>

          <!-- HITL Request: left-aligned, can expand -->
          <div v-else-if="item.item_type === 'hitl_request' && shouldShowHITLRequest(item)" class="flex justify-start">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              :show-actions="true"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <!-- Active: show full interactive UI -->
              <HITLContainer
                v-if="isActiveHITLRequest(item)"
                :chat-id="chat.id"
                :action="parseHITLAction(item)"
                @responded="handleHITLResponded"
              />
              <!-- Completed plan approval: show plan with approved status -->
              <div v-else-if="parseHITLAction(item)?.type === 'plan_approval'" class="bg-surface/80 rounded-xl p-3 border border-edge-subtle">
                <PlanApproval
                  :prompt="parseHITLAction(item)?.prompt || ''"
                  :plan-data="parseHITLAction(item)?.plan_data"
                  :completed="true"
                  :approved="findHITLResponse(item)?.approved"
                />
              </div>
              <!-- Completed v2_tool_permission: compact resolved state -->
              <div v-else-if="parseHITLAction(item)?.type === 'v2_tool_permission'" class="bg-surface/80 rounded-xl p-3 border border-edge-subtle">
                <V2PermissionPrompt
                  :action="parseHITLAction(item)"
                  :completed="true"
                  :response="findHITLResponse(item)"
                />
              </div>
              <!-- Completed ask_user: compact question/answer summary -->
              <div v-else-if="parseHITLAction(item)?.type === 'ask_user'" class="bg-surface/80 rounded-xl p-3 border border-edge-subtle">
                <AskUserPrompt
                  :action="parseHITLAction(item)"
                  :completed="true"
                  :response="findHITLResponse(item)"
                />
              </div>
            </ChatItemWrapper>
          </div>

          <!-- Completed HITL requests that we don't display individually -->
          <template v-else-if="item.item_type === 'hitl_request'"></template>

          <!-- HITL Response - hidden (completed HITL displayed inline above) -->
          <template v-else-if="item.item_type === 'hitl_response'"></template>

          <!-- Skill injection - subtle indicator (legacy items carry stimpack_* metadata keys) -->
          <div v-else-if="item.item_type === 'stimpack_injection'" class="flex justify-center py-1">
            <span class="text-[11px] text-content-muted italic">Activated skill: {{ item.item_metadata?.skill_display_name || item.item_metadata?.skill_name || item.item_metadata?.stimpack_display_name || item.item_metadata?.stimpack_name || 'unknown' }}</span>
          </div>

          <!-- Empty assistant message (skip) -->
          <template v-else-if="item.item_type === 'assistant_message'">
            <!-- Intentionally empty - no content to display yet -->
          </template>

          <!-- Unknown type -->
          <div v-else class="flex justify-center">
            <ChatItemWrapper
              :item-id="item.id"
              align="left"
              @branch="branchFromHere(item.id)" @delete-from-here="deleteFromHere(item.id)"
              @delete="deleteItem(item.id)"
              @debug="showDebugForItem(item.id)"
            >
              <div class="bg-surface text-content-muted rounded-lg px-4 py-2 text-sm">
                {{ item.item_type }}
              </div>
            </ChatItemWrapper>
          </div>
          </div>

          <!-- Typing indicator when agent is actively running -->
          <div v-if="showAgentTypingIndicator" class="flex justify-start">
            <div class="bg-surface text-content-tertiary rounded-lg px-4 py-3">
              <div class="flex items-center gap-2">
                <div class="flex items-center gap-1">
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                </div>
                <!-- Show running tool names -->
                <span v-if="runningNodes.length > 0" class="text-xs text-content-muted">
                  {{ uniqueRunningNodeNames.join(', ') }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      </template>
    </div>

    <!-- Queued Messages (when agent is busy) -->
    <div v-if="messageQueue.length > 0" class="border-t border-edge/50 px-4 py-2 flex flex-col gap-2">
      <div
        v-for="(queuedMsg, index) in messageQueue"
        :key="index"
        class="flex justify-end"
      >
        <div class="flex items-start gap-2 max-w-[60%]">
          <div class="bg-surface-raised/50 text-content-tertiary rounded-lg px-3 py-2 text-sm">
            <!-- Queued attachments preview -->
            <div v-if="queuedMsg.attachments.length > 0" class="flex gap-1 mb-1">
              <div
                v-for="(attachment, aIdx) in queuedMsg.attachments"
                :key="aIdx"
                class="w-8 h-8 rounded overflow-hidden flex-shrink-0"
              >
                <!-- Deleted asset placeholder (deleted flag from API or broken during session) -->
                <div
                  v-if="attachment.deleted || (attachment.media_id && isMediaBroken(attachment.media_id))"
                  class="w-full h-full bg-surface flex items-center justify-center"
                  title="Asset deleted"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
                    <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clip-rule="evenodd" />
                  </svg>
                </div>
                <!-- Library media (has media_id) -->
                <MediaImage
                  v-else-if="attachment.media_id"
                  :mediaId="attachment.media_id"
                  :thumbnail="true"
                  :thumbnailSize="64"
                  containerClass="w-full h-full"
                  @error="handleMediaLoadError(attachment.media_id)"
                />
                <!-- Reference file (path only) -->
                <AppImage
                  v-else
                  :src="getAttachmentThumbnail(attachment)"
                  containerClass="w-full h-full"
                />
              </div>
            </div>
            <!-- Queued message refs — same parse as sent bubbles so the
                 user sees chips, not the raw markdown transport. -->
            <div
              v-if="parseQueuedRefs(queuedMsg.text).length > 0"
              class="flex flex-wrap gap-1 mb-1"
            >
              <FlowRefChip
                v-for="r in parseQueuedRefs(queuedMsg.text)"
                :key="r.refKey"
                :label="r.label"
                :breadcrumb="r.breadcrumb"
                variant="composer"
              />
            </div>
            <span v-if="stripQueuedRefs(queuedMsg.text)">{{ stripQueuedRefs(queuedMsg.text) }}</span>
            <span v-else-if="!queuedMsg.text && queuedMsg.attachments.length > 0" class="italic text-content-muted">Image only</span>
            <span v-else-if="!stripQueuedRefs(queuedMsg.text) && parseQueuedRefs(queuedMsg.text).length > 0" class="italic text-content-muted">(references only)</span>
          </div>
          <button
            @click="removeQueuedMessage(index)"
            class="p-1 rounded hover:bg-surface-raised text-content-muted hover:text-content-secondary flex-shrink-0"
            title="Remove from queue"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Dev mode: session token usage bar -->
    <div v-if="devModeRef && sessionTokenTotals.turns > 0" class="px-4 py-1 flex-shrink-0 flex items-center gap-3 text-[10px] font-mono text-content-muted border-t border-edge bg-surface/50">
      <span v-if="sessionTokenTotals.model" class="text-content-secondary">{{ sessionTokenTotals.model }}</span>
      <span>{{ formatTokenCount(sessionTokenTotals.prompt_tokens) }} in / {{ formatTokenCount(sessionTokenTotals.completion_tokens) }} out<template v-if="sessionTokenTotals.reasoning_tokens"> / {{ formatTokenCount(sessionTokenTotals.reasoning_tokens) }} reasoning</template></span>
      <span v-if="sessionTokenTotals.cache_read_input_tokens" class="text-teal-500">cache {{ formatTokenCount(sessionTokenTotals.cache_read_input_tokens) }} hit<template v-if="sessionTokenTotals.cache_creation_input_tokens"> / {{ formatTokenCount(sessionTokenTotals.cache_creation_input_tokens) }} write</template></span>
      <span v-if="sessionTokenTotals.avg_tps" class="text-content-secondary">{{ sessionTokenTotals.avg_tps.toFixed(1) }} t/s avg</span>
      <span class="text-content-muted/60">{{ sessionTokenTotals.turns }} {{ sessionTokenTotals.turns === 1 ? 'turn' : 'turns' }}</span>
      <!-- Context window meter — centered between left stats and right quota -->
      <div v-if="llmUsage?.context_tokens" class="ml-auto flex items-center gap-1.5">
        <span :class="tokenUsagePercent > 90 ? 'text-red-400' : tokenUsagePercent > 70 ? 'text-amber-400' : 'text-content-muted'">ctx {{ formatTokenCount(llmUsage.context_tokens) }}/{{ formatTokenCount(contextLimit) }}</span>
        <div class="w-12 h-1 bg-black/10 dark:bg-white/15 rounded-full overflow-hidden">
          <div class="h-full rounded-full transition-all duration-300" :class="tokenUsagePercent > 90 ? 'bg-red-500' : tokenUsagePercent > 70 ? 'bg-amber-500' : 'bg-blue-500'" :style="{ width: tokenUsagePercent + '%' }"></div>
        </div>
      </div>
      <!-- Stimma Cloud quota (piggybacked on LLM responses) — right-justified with mini bars -->
      <div v-if="llmUsage?.quota" class="ml-auto flex items-center gap-3">
        <div v-if="llmUsage.quota.session_percent != null" class="flex items-center gap-1.5">
          <span :class="llmUsage.quota.session_percent > 95 ? 'text-red-400' : llmUsage.quota.session_percent > 80 ? 'text-amber-400' : 'text-content-muted'">session {{ llmUsage.quota.session_percent }}%</span>
          <div class="w-10 h-1 bg-black/10 dark:bg-white/15 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all duration-300" :class="llmUsage.quota.session_percent > 95 ? 'bg-red-500' : llmUsage.quota.session_percent > 80 ? 'bg-amber-500' : 'bg-teal-500'" :style="{ width: llmUsage.quota.session_percent + '%' }"></div>
          </div>
        </div>
        <div v-if="llmUsage.quota.weekly_percent != null" class="flex items-center gap-1.5">
          <span :class="llmUsage.quota.weekly_percent > 95 ? 'text-red-400' : llmUsage.quota.weekly_percent > 80 ? 'text-amber-400' : 'text-content-muted'">week {{ llmUsage.quota.weekly_percent }}%</span>
          <div class="w-10 h-1 bg-black/10 dark:bg-white/15 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all duration-300" :class="llmUsage.quota.weekly_percent > 95 ? 'bg-red-500' : llmUsage.quota.weekly_percent > 80 ? 'bg-amber-500' : 'bg-teal-500'" :style="{ width: llmUsage.quota.weekly_percent + '%' }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <div class="px-4 pb-4 pt-2 flex-shrink-0">
      <div
        v-if="chatInterrupted"
        class="mb-2 flex items-center justify-between gap-3 px-3 py-2 rounded-md border border-amber-500/40 bg-amber-500/[0.08]"
      >
        <div class="flex items-center gap-2 min-w-0">
          <ExclamationTriangleIcon class="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0" />
          <span class="text-sm text-amber-700 dark:text-amber-300 truncate">Interrupted by app restart</span>
        </div>
        <button
          @click="continueAfterInterrupt"
          class="flex-shrink-0 px-3 py-1 text-xs font-medium rounded-md bg-amber-500/20 hover:bg-amber-500/30 text-amber-700 dark:text-amber-200 border border-amber-500/40 transition-colors"
        >
          Continue
        </button>
      </div>
      <div
        v-if="modelUnavailableMessage && !showNoModelSetupHero"
        class="mb-2 text-xs text-amber-500"
      >
        {{ modelUnavailableMessage }}
      </div>
      <ChatInputBox
        ref="chatInputBoxRef"
        v-model="messageInput"
        :attachments="inputAttachments"
        :voice-surface="chat?.flow_id ? 'flow_chat' : 'main_chat'"
        :disabled="sending"
        @update:attachments="inputAttachments = $event"
        @submit="handleEnterKey"
        @keydown="handleKeyDown"
      >
        <template #context-header>
          <slot name="context-header" />
        </template>
        <template #toolbar-extra>
          <SkillsMenuButton
            :skills="eligibleSkills"
            :active-keys="invokedSkillKeySet"
            :invoking="invokingSkillName"
            @activate="activateSkill"
          />
        </template>
        <template #model-picker>
          <ChatModelPicker
            v-if="showModelPicker"
            :model-slug="chat.model_slug"
            :chat-id="chatId"
            :project-id="chat.project_id"
            :disabled="noUsableChatModels"
            disabled-label="Model unavailable"
            @update:model-slug="updateChatModel"
          />
        </template>
        <template #actions>
          <button
            v-if="showStopButton"
            @click="stopAgent"
            class="w-8 h-8 flex items-center justify-center rounded-full bg-content text-surface transition-colors hover:opacity-80"
            title="Stop"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-3.5 h-3.5">
              <rect x="6" y="6" width="12" height="12" rx="1" />
            </svg>
          </button>
          <button
            v-else
            @click="sendMessage()"
            :disabled="(!messageInput.trim() && inputAttachments.length === 0) || sending || isChatModelUnavailable"
            class="w-8 h-8 flex items-center justify-center rounded-full bg-content text-surface transition-colors disabled:opacity-30"
            :title="modelUnavailableMessage || 'Send'"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
              <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)" />
            </svg>
          </button>
        </template>
      </ChatInputBox>
    </div>

    <!-- Delete Confirmation Modal -->
    <ConfirmModal
      :show="showDeleteModal"
      title="Delete Chat"
      :message="deleteConfirmMessage"
      confirm-text="Delete"
      cancel-text="Cancel"
      @confirm="deleteChat"
      @cancel="showDeleteModal = false"
    />


    <!-- Job Info Modal -->
    <JobInfoModal
      :show="showJobInfoModal"
      :job="selectedJob"
      @close="closeJobModals"
    />

    <!-- Job Error Modal -->
    <JobErrorModal
      :show="showJobErrorModal"
      :job="selectedJob"
      @close="closeJobModals"
      @retry="retryJob"
      @dismiss="dismissJob"
    />

    <!-- Trace Modal -->
    <TraceModal
      :show="showTraceModal"
      :chat-id="chatId"
      :trace-id="selectedTraceId"
      :plan-id="tracePlanId"
      :tool-call-id="traceToolCallId"
      @close="showTraceModal = false; selectedTraceId = null; tracePlanId = null; traceToolCallId = null"
    />


    <!-- Slideshow Mode -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      @close="exitSlideshow"
      @compare-with-source="handleCompareFromSlideshow"
    />

    <!-- Compare Mode (overlays slideshow when active) -->
    <CompareMode
      v-if="compareState.active"
      :left-item="compareState.leftItem"
      :right-item="compareState.rightItem"
      :loading="compareState.loading"
      :error="compareState.error"
      @close="exitCompare"
      @swap="swapCompareImages"
    />
        </div>

        <!-- Settings Panel (toggle visibility from header) — suppressed when embedded -->
        <ChatSettingsPanel
          v-if="chat && !embedded"
          :chat-id="chat.id"
          :visible="settingsPanelVisible"
        />
      </div>

      <!-- Image strip (horizontal at bottom, spans chat + settings panel) -->
      <!-- TODO: Hidden for evaluation - remove 'false &&' to re-enable -->
      <ChatImageStrip
        v-if="false && liveChatMediaIds.length > 0"
        :media-ids="liveChatMediaIds"
        @open-slideshow="openStripSlideshow"
        @drag-media="handleStripDragStart"
      />
    </div>

    <!-- Context Menu (teleports to body) -->
    <!-- No @refresh handler - chat doesn't need to reload when media is trashed/restored -->
    <!-- But we do need to handle permanent deletes to remove the media from view -->
    <MediaContextMenu @permanent-delete="handleMediaPermanentDelete" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChatControlStrip from '../components/chat/ChatControlStrip.vue'
import ChatSettingsPanel from '../components/chat/ChatSettingsPanel.vue'
import { MediaImage, AppImage, MediaContextMenu } from '../components/media'
import ChatImageStrip from '../components/chat/ChatImageStrip.vue'
import ChatInputAttachments from '../components/chat/ChatInputAttachments.vue'
import ChatInputBox from '../components/chat/ChatInputBox.vue'
import SkillsMenuButton from '../components/chat/SkillsMenuButton.vue'
import FlowRefChip from '../components/flow/FlowRefChip.vue'
import { useFlowReferences, formatReferencesForMessage, parseMessageReferences, type FlowReference } from '../composables/useFlowReferences'
import { pendingMedia, consumePendingMedia } from '../composables/usePendingMedia'
import { useMediaDetailsModal } from '../composables/useMediaDetailsModal'
import ChatModelPicker from '../components/chat/ChatModelPicker.vue'
import { getApiBase, isTauri } from '../apiConfig'
import { useCloudAccount } from '../composables/useCloudAccount'
import { getCachedPin } from '../composables/usePinLock'
// Component name for KeepAlive
defineOptions({
  name: 'ChatView'
})
import MediaDisplay from '../components/chat/MediaDisplay.vue'
import GridGenerationDisplay from '../components/chat/GridGenerationDisplay.vue'
import ProgressDisplay from '../components/chat/ProgressDisplay.vue'
import AnalysisResult from '../components/chat/AnalysisResult.vue'
import ScoredResultsDisplay from '../components/chat/ScoredResultsDisplay.vue'
import ConfirmModal from '../components/ConfirmModal.vue'
import JobInfoModal from '../components/generation/JobInfoModal.vue'
import JobErrorModal from '../components/generation/JobErrorModal.vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import CompareMode from '../components/CompareMode.vue'
import { useCompare } from '../composables/useCompare'
import ConnectionError from '../components/ConnectionError.vue'
import HITLContainer from '../components/hitl/HITLContainer.vue'
import AskUserPrompt from '../components/hitl/AskUserPrompt.vue'
import PlanApproval from '../components/hitl/PlanApproval.vue'
import V2PermissionPrompt from '../components/hitl/V2PermissionPrompt.vue'
import PlanVisualization from '../components/PlanVisualization.vue'
import NotepadDisplay from '../components/chat/NotepadDisplay.vue'
import TraceModal from '../components/chat/TraceModal.vue'
import { copyToClipboard } from '../utils/clipboard'
import { addToast } from '../composables/useToasts'
import { signInWithBrowser, useAuth } from '../composables/useAuth'
import { useAvailableModels } from '../composables/useAvailableModels'
import {
  ClipboardDocumentListIcon,
  ListBulletIcon,
  ArrowPathIcon,
  ChartBarSquareIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  ChevronRightIcon,
  ExclamationTriangleIcon,
  ShieldExclamationIcon,
  ClockIcon,
  SparklesIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import ChatItemWrapper from '../components/chat/ChatItemWrapper.vue'
import ChatErrorDisclosure from '../components/chat/ChatErrorDisclosure.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useStimpacksApi } from '../composables/useStimpacksApi'
import { useSlideshow } from '../composables/useSlideshow'
import { getCurrentProfileId } from '../composables/useProfile'
import { makeProfileKey } from '../utils/storageKeys'
import { useWebSocket } from '../composables/useWebSocket'
import { marked } from 'marked'
import axios from 'axios'
import { devModeRef } from '../appConfig'
import { escapeHtmlAttribute, sanitizeHtml } from '../utils/sanitizeHtml'
import { formatTaskTypeLabel } from '../utils/taskTypeIcons'

const props = defineProps<{
  // Optional override for chat identity. When provided, this takes precedence
  // over route.params.id so the view can be embedded as a component (e.g.
  // inside the flow sidebar) without owning a route.
  chatId?: number | string | null
  // When true, hide the top control strip so the view fits inside a narrow
  // embedded context. Settings panel toggle is also suppressed since its
  // affordance lives on the control strip.
  embedded?: boolean
}>()

const route = useRoute()
const router = useRouter()
const { getMediaItem, getThumbnailUrl } = useMediaApi()
const { listSkills: listSkillsApi } = useStimpacksApi()
const { cloudBaseUrl } = useCloudAccount()
const { isAuthenticated } = useAuth()
const { models: availableModels, globalDefault, loading: modelsLoading, invalidateCache: invalidateModelCache, fetchModels: fetchAvailableModels, getResolvedModel } = useAvailableModels()
const { slideshowState, enterSlideshow, exitSlideshow } = useSlideshow()
const mediaDetailsModal = useMediaDetailsModal()
const { compareState, enterCompare, exitCompare, swapImages: swapCompareImages } = useCompare()

const chatId = ref(null)
const chat = ref(null)
const items = ref([])
const loading = ref(true)
const loadError = ref(false)
const brokenMediaIds = ref(new Set<number>()) // Track media that failed to load (404/deleted)
const hasMore = ref(false)
const messageInput = ref('')
const sending = ref(false)
const messageHistory = ref([])  // History of sent messages
const historyIndex = ref(-1)    // -1 = current input, 0+ = history position
const savedCurrentInput = ref('') // Saves current input when browsing history
const messagesContainer = ref(null)
const loadMoreSentinel = ref(null)
const loadMoreObserver = ref(null)
const chatInputBoxRef = ref(null)
const messageInputRef = computed(() => chatInputBoxRef.value?.textareaRef)
const textareaScrollRef = computed(() => chatInputBoxRef.value?.scrollWrapRef)
const agentRunning = ref(false)
const agentPlanning = ref(false)
const agentPaused = ref(false)
const runningNodes = ref([]) // Track currently running nodes: [{node_id, node_type, tool_name, display_name}]
const nodeStates = ref({}) // Track node execution states: { node_id: { status, display_name } }
const suppressingPostStop = ref(false) // When true, ignore chat_item_created until agent responds to stop
const rawPlanItemIds = reactive(new Set()) // Track which plan items are in "raw" mode
const GENERIC_CHAT_ERROR_MESSAGE = 'Something went wrong.'
const LLM_SETUP_ERROR_TYPES = new Set([
  'llm_not_configured',
  'llm_not_logged_in',
  'llm_subscription_required',
  'llm_cloud_unreachable',
  'llm_local_missing',
  'llm_model_missing',
  'subscription_required',
])
const showDeleteModal = ref(false)
const showJobInfoModal = ref(false)
const showJobErrorModal = ref(false)
const showTraceModal = ref(false)
const selectedTraceId = ref(null)
const tracePlanId = ref(null)  // Filter traces by plan ID
const traceToolCallId = ref(null)  // Filter traces by tool_call_id (for delegate subagent traces)
const chatTraces = ref([])  // All traces for this chat
const selectedJob = ref(null)
const viewMode = ref('chat') // 'chat' or 'raw'
// Migrate legacy unscoped key
const _legacyChatSettingsKey = 'chatSettingsPanelVisible'
const _chatSettingsKey = makeProfileKey('chatSettingsPanelVisible')
if (localStorage.getItem(_legacyChatSettingsKey) !== null) {
  localStorage.setItem(_chatSettingsKey, localStorage.getItem(_legacyChatSettingsKey))
  localStorage.removeItem(_legacyChatSettingsKey)
}
const settingsPanelVisible = ref(localStorage.getItem(_chatSettingsKey) === 'true')
const focusedItemId = ref(null) // ID of item to focus in raw view
const debugMessages = ref(null) // Debug: what LLM sees
const debugSystemPrompt = ref(null) // The system prompt sent to agent
const debugAgentVersion = ref(null) // Agent version used for debug payload
const systemPromptExpanded = ref(false) // Toggle for system prompt display
const debugLoading = ref(false)
const llmUsage = ref(null) // Latest LLM usage stats from WebSocket
const generationProgress = ref(null) // { current: number, total: number } | null
const CHAT_AUTO_DELETE_DURATION = 'never'
const availableMarkers = ref([]) // Markers available for tagging
const mediaMarkers = ref({}) // Map of media_id -> array of markers
const selectedMediaIds = ref([]) // Media IDs selected for "that one" references
const inputAttachments = ref([]) // Images attached to the message input
// inputDragging is now managed by ChatInputBox
const editingItemId = ref(null) // ID of item being edited, null if not editing
const editingText = ref('') // Current text in inline editor
const editingMinSize = ref({ width: 0, height: 0 }) // Original bubble size when editing started
const messageQueue = ref([]) // Queued messages when agent is busy: [{text, attachments}]
let lastSendStartedAt = 0 // When the last POST /items started (watchdog grace period)
let queueBackoffUntil = 0 // Don't retry a failed queued send before this time
let queueWatchdogTimer = null // Interval that reconciles state while messages are queued
// uploadInput is now managed by ChatInputBox

// WebSocket - use shared singleton composable
const { on: onWsEvent, connected: wsConnected } = useWebSocket()
const wsUnsubscribes = [] // Store unsubscribe functions for cleanup

// Agent status computed
const agentStatus = computed(() => {
  if (agentPlanning.value) return 'planning'
  if (agentRunning.value) return 'generating'
  if (agentPaused.value) return 'paused'
  return 'idle'
})

const hasActiveHITLRequest = computed(() => (
  items.value.some(item => item.item_type === 'hitl_request' && isActiveHITLRequest(item))
))

const showAgentTypingIndicator = computed(() => (
  (agentRunning.value || agentPlanning.value) && !hasActiveHITLRequest.value && !hasRunningActivityGroup.value
))

const showStopButton = computed(() => (
  (agentRunning.value || agentPlanning.value) && !hasActiveHITLRequest.value
))

// True when the chat was interrupted by an app/server restart and is now idle:
// the most recent activity ended in a failed thinking step (zero-duration =
// cleanup-marked) or an orphaned tool_call with an "Interrupted by server
// restart" result, with no user_message after it. Hidden while the agent is
// active so it doesn't flash during normal turns.
const chatInterrupted = computed(() => {
  if (agentRunning.value || agentPlanning.value) return false
  if (hasActiveHITLRequest.value) return false
  for (let i = items.value.length - 1; i >= 0; i--) {
    const item = items.value[i]
    if (item.item_type === 'user_message') return false
    if (item.item_type === 'assistant_message' && isThinkingInterrupted(item)) return true
    if (item.item_type === 'tool_result') {
      const payload = typeof item.tool_result === 'string'
        ? (() => { try { return JSON.parse(item.tool_result) } catch { return null } })()
        : item.tool_result
      if (payload?.error && typeof payload.error === 'string'
          && payload.error.includes('Interrupted by server restart')) return true
    }
  }
  return false
})

// Remove null/undefined values from an object recursively
function stripNulls(obj) {
  if (Array.isArray(obj)) {
    return obj.map(stripNulls).filter(v => v !== null && v !== undefined)
  }
  if (obj !== null && typeof obj === 'object') {
    const result = {}
    for (const [key, value] of Object.entries(obj)) {
      if (value !== null && value !== undefined) {
        result[key] = stripNulls(value)
      }
    }
    return result
  }
  return obj
}

// Format node name for display in typing indicator (progressive form)
function formatNodeName(node) {
  let name
  // Prefer display_name_active for progress indicator (e.g., "Generating Images")
  if (node.display_name_active) {
    name = node.display_name_active
  } else if (node.display_name) {
    name = node.display_name
  } else if (node.tool_name) {
    name = node.tool_name.replace(/_/g, ' ')
  } else if (node.node_type) {
    name = node.node_type.replace(/_/g, ' ')
  } else {
    name = node.node_id
  }
  // Append progress if available (e.g., "Processing 9 Items (3/9)")
  if (node.current != null && node.total != null) {
    name += ` (${node.current}/${node.total})`
  }
  return name
}

// Get unique running node names (deduped by display_name_active)
const uniqueRunningNodeNames = computed(() => {
  const seen = new Set()
  const names = []
  for (const node of runningNodes.value) {
    const name = formatNodeName(node)
    if (!seen.has(name)) {
      seen.add(name)
      names.push(name)
    }
  }
  return names
})

// Format JSON with syntax highlighting
function formatJsonWithHighlighting(obj) {
  const cleaned = stripNulls(obj)
  const json = JSON.stringify(cleaned, null, 2)

  // Apply syntax highlighting via regex replacements
  return json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Keys (before colon)
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    // String values
    .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
    // Numbers
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
    // Booleans
    .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
}

// HITL (Human-in-the-loop) helpers
const activeHITLNodeId = ref(null)

function parseHITLAction(item) {
  if (!item.item_metadata) return null
  try {
    return typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
  } catch (e) {
    console.error('Failed to parse HITL action:', e)
    return null
  }
}

function parseMediaDisplayData(item) {
  if (!item.item_metadata) return { rows: [], status: 'pending' }
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return metadata.display_data || { rows: [], status: 'pending' }
  } catch (e) {
    console.error('Failed to parse media display data:', e)
    return { rows: [], status: 'pending' }
  }
}

function parseProgressDisplayData(item) {
  const fallback = { title: null, status: 'in_progress', current: 0, total: 0, previews: [] }
  if (!item.item_metadata) return fallback
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return metadata.display_data || fallback
  } catch (e) {
    console.error('Failed to parse progress display data:', e)
    return fallback
  }
}

function parseScoredResultsData(item) {
  if (!item.item_metadata) return { criteria: '', items: [] }
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return metadata.scored_data || { criteria: '', items: [] }
  } catch (e) {
    console.error('Failed to parse scored results data:', e)
    return { criteria: '', items: [] }
  }
}

function parseGridGenerationData(item) {
  if (!item.item_metadata) return { cells: [], status: 'pending', rows: 0, cols: 0 }
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return metadata.display_data || { cells: [], status: 'pending', rows: 0, cols: 0 }
  } catch (e) {
    console.error('Failed to parse grid generation data:', e)
    return { cells: [], status: 'pending', rows: 0, cols: 0 }
  }
}

function parseAnalysisData(item) {
  if (!item.item_metadata) return { description: 'No analysis data' }
  try {
    const metadata = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return metadata.analysis_data || { description: 'No analysis data' }
  } catch (e) {
    console.error('Failed to parse analysis data:', e)
    return { description: 'Failed to load analysis' }
  }
}

function isActiveHITLRequest(item) {
  const action = parseHITLAction(item)
  if (!action) return false
  const itemIdx = items.value.findIndex(i => i.id === item.id)
  if (itemIdx < 0) return false
  for (let i = itemIdx + 1; i < items.value.length; i++) {
    if (items.value[i].item_type === 'hitl_response') {
      return false
    }
  }
  return true
}

function shouldShowHITLRequest(item) {
  const action = parseHITLAction(item)
  if (!action) return false
  // Hide completed v1 tool permission requests (result captured in response)
  if (action.type === 'request_tool_permission' && !isActiveHITLRequest(item)) {
    return false
  }
  // Always show v2_tool_permission (both active and completed)
  // Always show plan_approval (both active and completed)
  return true
}

function findHITLResponse(requestItem) {
  const itemIdx = items.value.findIndex(i => i.id === requestItem.id)
  if (itemIdx < 0) return null
  for (let i = itemIdx + 1; i < items.value.length; i++) {
    if (items.value[i].item_type === 'hitl_response') {
      const meta = items.value[i].item_metadata
      try {
        const parsed = typeof meta === 'string' ? JSON.parse(meta) : meta
        // v2_tool_permission stores response flat: { approved, scope }
        // plan_approval stores it nested: { response: { approved, ... } }
        return parsed?.response || parsed || null
      } catch {
        return null
      }
    }
  }
  return null
}

function getToolCallErrorMessage(toolCallItem) {
  const result = findToolResult(toolCallItem)
  if (!result?.tool_result) return ''
  const payload = typeof result.tool_result === 'string' ? (() => { try { return JSON.parse(result.tool_result) } catch { return result.tool_result } })() : result.tool_result
  if (typeof payload === 'object') return payload.description || payload.error || ''
  return String(payload)
}

function isToolResultInActivityGroup(toolResultItem) {
  // Check if this tool_result's parent tool_call is inside an activity group
  const toolCallId = toolResultItem.tool_call_id
  if (!toolCallId) return false
  const parentToolCall = items.value.find(i => i.item_type === 'tool_call' && i.tool_call_id === toolCallId)
  if (!parentToolCall) return false
  return !!activityGroupInfo.value.get(parentToolCall.id)
}

function findToolResult(toolCallItem) {
  const itemIdx = items.value.findIndex(i => i.id === toolCallItem.id)
  if (itemIdx < 0) return null
  for (let i = itemIdx + 1; i < items.value.length; i++) {
    const candidate = items.value[i]
    if (candidate.item_type === 'tool_result' && candidate.tool_call_id === toolCallItem.tool_call_id) {
      return candidate
    }
    if (candidate.item_type === 'tool_call' && candidate.tool_call_id === toolCallItem.tool_call_id) {
      break
    }
  }
  return null
}

function getToolCallResultData(toolCallItem) {
  const result = findToolResult(toolCallItem)
  if (!result) return null
  const payload = result.tool_result
  if (!payload) return null
  if (typeof payload === 'object') return payload
  try {
    return JSON.parse(payload)
  } catch {
    return payload
  }
}

function getToolCallStatus(toolCallItem) {
  const resultData = getToolCallResultData(toolCallItem)
  if (!resultData) return 'running'
  if (typeof resultData === 'object' && resultData?.error) return 'failed'
  return 'completed'
}

function getToolCallStatusLabel(toolCallItem) {
  const status = getToolCallStatus(toolCallItem)
  if (status === 'failed') return 'Failed'
  return 'Running'
}

// Friendly display names for agent tools (avoid developer jargon)
const TOOL_DISPLAY_NAMES = {
  call_tool: null,       // Special: uses tool_args._display_name or tool_id
  run_code: 'Running Script',
  bash: 'Running Command',
  ask_user: 'Asking You',
  browse_web: 'Browsing Web',
  library: null,         // Special: varies by action arg
  skill: null,           // Special: "Skill: <display_name>"
  stimpack: null,        // backward compat for old chats: "Skill: <display_name>"
  delegate: null,        // Special: shows specialist or truncated task
  glob: 'Finding Files',
  grep: 'Searching Files',
  read_file: 'Reading File',
  write_file: 'Saving File',
  edit_file: 'Editing File',
  create_parameter_sweep: 'Creating Parameter Sweep',
  assemble_grid: 'Creating Grid',  // backward compat for old chats
  assemble_set: 'Creating Set',
  create_layout: 'Creating Layout',
  render_html: 'Rendering Layout',  // backward compat for old chats
  analyze_flow: 'Analyzing Flow',
  flow_inspect: 'Analyzing Flow',  // backward compat: renamed from flow_inspect
  flow_update: 'Updating Flow',
}

// Library action → display copy
const LIBRARY_ACTION_NAMES = {
  search: 'Searching Library',
  browse: 'Browsing Library',
  browse_schema: 'Browsing Library',
  browse_options: 'Browsing Library',
  get: 'Looking Up Asset',
  save: 'Saving to Library',
  lineage: 'Checking Lineage',
  tag: 'Tagging',
  marker: 'Marking',
  board: 'Organizing Board',
}

// Infrastructure tools hidden from pill summary (still shown in expanded timeline)
const HIDDEN_TOOLS = new Set(['list_tools', 'get_schema', 'discover', 'view_image', 'notepad', 'sdk_help', 'show'])

// All known display names (for pill and expanded timeline)
const ALL_TOOL_DISPLAY_NAMES = {
  ...Object.fromEntries(Object.entries(TOOL_DISPLAY_NAMES).filter(([, v]) => v !== null)),
  // Hidden tools get friendly names in expanded timeline
  list_tools: 'Exploring Tools',
  get_schema: 'Exploring Tools',
  discover: 'Exploring Tools',
  view_image: 'Viewing Image',
  notepad: 'Taking Notes',
  sdk_help: 'Reading Docs',
  show: 'Showing Work',
}

function formatToolCallName(name) {
  if (!name) return 'Tool'
  if (ALL_TOOL_DISPLAY_NAMES[name]) return ALL_TOOL_DISPLAY_NAMES[name]
  const acronyms = { html: 'HTML', css: 'CSS', url: 'URL', api: 'API', json: 'JSON', id: 'ID', stp: 'STP' }
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\b\w+\b/g, w => acronyms[w.toLowerCase()] || w)
}

// Format a raw tool_id like "comfyui:flux-klein-9b" into "Flux Klein 9B"
function formatToolId(toolId) {
  // Strip provider prefix (e.g. "comfyui:" or "a1111:")
  const name = toolId.includes(':') ? toolId.split(':').slice(1).join(':') : toolId
  return name.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// Get display name for a tool_call item (uses tool_args for call_tool)
function getToolCallDisplayName(toolCallItem) {
  const args = toolCallItem.tool_args || {}

  if (toolCallItem.tool_name === 'call_tool') {
    if (args._display_name) return String(args._display_name)
    const toolId = args.tool_id
    if (toolId) return formatToolId(String(toolId))
    return 'Tool'
  }
  if (toolCallItem.tool_name === 'skill' || toolCallItem.tool_name === 'stimpack') {
    // Fallback shows only the leaf of a pack-qualified name ("pack/skill")
    const leaf = args.name ? String(args.name).split('/').pop() : null
    const displayName = args._display_name || (leaf ? formatToolId(leaf) : null)
    return displayName ? `Skill: ${displayName}` : 'Skill'
  }
  if (toolCallItem.tool_name === 'delegate') {
    if (args.specialist) return formatToolId(String(args.specialist))
    const task = String(args.task || '').trim()
    if (task) {
      const short = task.length > 40 ? task.slice(0, 40) + '…' : task
      return `Delegating: ${short}`
    }
    return 'Delegating Task'
  }
  if (toolCallItem.tool_name === 'library') {
    const action = (args.action || '').toLowerCase().trim()
    return LIBRARY_ACTION_NAMES[action] || 'Library'
  }
  return formatToolCallName(toolCallItem.tool_name)
}

function getToolCallPreview(toolCallItem) {
  const args = toolCallItem.tool_args || {}
  switch (toolCallItem.tool_name) {
    case 'run_code':
      return String(args.code || '').trim().split('\n')[0] || 'Running Python code'
    case 'bash':
      return String(args.command || '').trim() || 'Running shell command'
    case 'browse_web':
      if (args.action === 'fetch') return String(args.url || '').trim() || 'Fetching URL'
      return String(args.query || '').trim() || 'Searching the web'
    case 'ask_user':
      return String(args.question || '').trim() || 'Waiting for user input'
    case 'show':
      return ''
    case 'call_tool': {
      // Show task type or prompt snippet instead of raw tool_id
      const taskType = args._task_type || args.inputs?._task_type
      if (taskType) return formatTaskTypeLabel(String(taskType))
      const prompt = args.inputs?.prompt || args.inputs?.positive_prompt
      if (prompt) return String(prompt).slice(0, 60)
      return ''
    }
    default:
      return ''
  }
}

function getToolCallDetails(toolCallItem) {
  const args = toolCallItem.tool_args || {}
  if (toolCallItem.tool_name === 'run_code') return String(args.code || '').trim()
  if (toolCallItem.tool_name === 'bash') return String(args.command || '').trim()
  if (toolCallItem.tool_name === 'browse_web') {
    if (args.action === 'fetch') return String(args.url || '').trim()
    return String(args.query || '').trim()
  }
  if (toolCallItem.tool_name === 'ask_user') return String(args.question || '').trim()
  if (toolCallItem.tool_name === 'create_layout' || toolCallItem.tool_name === 'render_html') {
    let detail = String(args.html || '').trim()
    if (args.css) detail += '\n\n/* --- CSS --- */\n' + String(args.css).trim()
    return detail
  }
  try {
    const text = JSON.stringify(args, null, 2)
    return text === '{}' ? '' : text
  } catch {
    return ''
  }
}

function getToolCallDetailKind(toolCallItem) {
  if (toolCallItem.tool_name === 'run_code' || toolCallItem.tool_name === 'bash' || toolCallItem.tool_name === 'create_layout' || toolCallItem.tool_name === 'render_html') return 'code'
  const details = getToolCallDetails(toolCallItem)
  if (details && details.startsWith('{')) return 'json'
  return 'text'
}

function getToolCallLanguage(toolCallItem) {
  if (toolCallItem.tool_name === 'run_code') return 'python'
  if (toolCallItem.tool_name === 'bash') return 'bash'
  if (toolCallItem.tool_name === 'create_layout' || toolCallItem.tool_name === 'render_html') return 'html'
  return 'text'
}

function formatToolCallJson(toolCallItem) {
  const details = getToolCallDetails(toolCallItem)
  try {
    const parsed = JSON.parse(details)
    return formatJsonWithHighlighting({ tool_args: parsed })
  } catch {
    return escapeHtml(details)
  }
}

function formatToolResultJson(toolCallItem) {
  const resultData = getToolCallResultData(toolCallItem)
  if (!resultData) return ''
  try {
    return formatJsonWithHighlighting({ tool_result: resultData })
  } catch {
    return escapeHtml(String(resultData))
  }
}

// ─── Activity Group System ───
// Groups consecutive thinking + tool call items into collapsible activity blocks

const expandedActivityGroups = ref(new Set())
const expandedDelegates = ref(new Set())  // Track which delegate details the user has expanded/collapsed
const autoExpandedDelegates = new Set()   // Track which delegates we've auto-expanded (not reactive, just bookkeeping)

function isVisibleActivityItem(item) {
  // Thinking-only assistant messages
  if (item.item_type === 'assistant_message' && hasThinking(item) && !getDisplayText(item)) return true
  // Tool calls
  if (item.item_type === 'tool_call') return true
  return false
}

function isInvisiblePassthroughItem(item) {
  // Items that are already hidden in the UI and shouldn't break activity groups
  if (item.item_type === 'tool_result') return true
  if (item.item_type === 'assistant_message' && !hasThinking(item) && !getDisplayText(item)) return true
  if (item.item_type === 'hitl_response') return true
  if (item.item_type === 'hitl_request' && !shouldShowHITLRequest(item)) return true
  // Output items rendered elsewhere but shouldn't break tool call grouping
  if (item.item_type === 'media_display') return true
  if (item.item_type === 'progress_display') return true
  if (item.item_type === 'generated_media') return true
  if (item.item_type === 'grid_generation') return true
  if (item.item_type === 'scored_results') return true
  if (item.item_type === 'notepad_display') return true
  if (item.item_type === 'stimpack_injection') return true
  return false
}

// Filter out child items (subagent activity) from the main list
const topLevelItems = computed(() => {
  return items.value.filter(item => !item.parent_item_id)
})

// Skills menu on the chat input — the one place skills are seen/activated.
// Regular chats list chat-eligible skills; embedded (flow) chats list
// flow-eligible ones. Activation state comes from stimpack_injection items
// (legacy items carry stimpack_* metadata keys).
const invokedSkillKeySet = computed(() => {
  const keys = new Set()
  for (const item of items.value) {
    if (item.item_type !== 'stimpack_injection') continue
    const meta = item.item_metadata || {}
    const name = meta.skill_name || meta.stimpack_name
    if (name) keys.add(name)
  }
  return keys
})

const eligibleSkills = ref([])
const invokingSkillName = ref(null)

async function loadEligibleSkills() {
  try {
    const all = await listSkillsApi()
    const env = props.embedded ? 'flow' : 'chat'
    eligibleSkills.value = all.filter(s => s.environments?.[env])
  } catch (err) {
    console.error('Failed to load skills:', err)
  }
}

async function activateSkill(name) {
  invokingSkillName.value = name
  try {
    // The resulting stimpack_injection item arrives via WebSocket and flips
    // the status dot through invokedSkillKeySet.
    await fetch(`/api/chats/${chatId.value}/invoke-skill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  } catch (err) {
    console.error('Failed to activate skill:', err)
  } finally {
    invokingSkillName.value = null
  }
}

function handleSkillsChanged() {
  loadEligibleSkills()
}

// Get child items for a given parent (delegate tool_call)
function getChildItems(parentItemId) {
  return items.value.filter(item => item.parent_item_id === parentItemId)
}

// Get visible activity items for a delegate's nested timeline
function getDelegateActivityItems(parentItemId) {
  const children = getChildItems(parentItemId)
  return children.filter(item => {
    if (item.item_type === 'tool_call') return true
    if (item.item_type === 'assistant_message' && hasThinking(item)) return true
    return false
  })
}

// Get delegate nested activity summary (mirrors getActivityGroupSummaryRaw)
function getDelegateActivitySummary(parentItemId) {
  const children = getChildItems(parentItemId)
  const toolNames = []
  let hasRunningTool = false
  let hasRunningThinking = false

  for (const item of children) {
    if (item.item_type === 'tool_call') {
      if (getDelegateChildToolStatus(item, children) === 'running') hasRunningTool = true
      if (HIDDEN_TOOLS.has(item.tool_name)) continue
      const displayName = getToolCallDisplayName(item)
      if (toolNames.length === 0 || toolNames[toolNames.length - 1] !== displayName) {
        toolNames.push(displayName)
      }
    }
    if (item.item_type === 'assistant_message' && hasThinking(item)) {
      if (isThinkingInProgress(item)) {
        hasRunningThinking = true
      }
    }
  }

  const isRunning = hasRunningTool || hasRunningThinking
  return { toolNames, isRunning, hasRunningThinking }
}

// Find tool result among child items (not main items list)
function getDelegateChildToolStatus(toolCallItem, children) {
  const result = children.find(
    c => c.item_type === 'tool_result' && c.tool_call_id === toolCallItem.tool_call_id
  )
  if (!result) return 'running'
  const payload = result.tool_result
  if (!payload) return 'running'
  let parsed = payload
  if (typeof payload === 'string') {
    try { parsed = JSON.parse(payload) } catch { return 'completed' }
  }
  if (typeof parsed === 'object' && parsed?.error) return 'failed'
  return 'completed'
}

// Get details (args) for a delegate child tool call — reuse the same logic as parent
function getDelegateChildToolDetails(toolCallItem) {
  return getToolCallDetails(toolCallItem)
}

// Get error message for a failed delegate child tool call
function getDelegateChildToolError(toolCallItem) {
  const children = getChildItems(toolCallItem.parent_item_id)
  const result = children.find(
    c => c.item_type === 'tool_result' && c.tool_call_id === toolCallItem.tool_call_id
  )
  if (!result?.tool_result) return ''
  const payload = typeof result.tool_result === 'string'
    ? (() => { try { return JSON.parse(result.tool_result) } catch { return result.tool_result } })()
    : result.tool_result
  if (typeof payload === 'object') return payload.description || payload.error || ''
  return String(payload)
}

const activityGroupInfo = computed(() => {
  const map = new Map()
  let currentGroup = null

  for (const item of topLevelItems.value) {
    if (isVisibleActivityItem(item)) {
      if (!currentGroup) {
        currentGroup = { id: `ag-${item.id}`, items: [], firstId: item.id }
      }
      currentGroup.items.push(item)
      map.set(item.id, currentGroup)
    } else if (isInvisiblePassthroughItem(item) && currentGroup) {
      // Skip over invisible items without breaking the group
      continue
    } else {
      currentGroup = null
    }
  }

  return map
})

function getActivityGroup(itemId) {
  return activityGroupInfo.value.get(itemId)
}

// Filter out activity items that would render as blank (e.g. thinking with no content and not in progress)
function getVisibleActivityItems(group) {
  return group.items.filter(item => {
    if (item.item_type === 'tool_call') return true
    if (item.item_type === 'assistant_message' && hasThinking(item)) {
      return !!getThinkingContent(item) || isThinkingInProgress(item)
    }
    return false
  })
}

function isFirstInActivityGroup(itemId) {
  const group = activityGroupInfo.value.get(itemId)
  return group && group.firstId === itemId
}

function toggleActivityGroup(groupId) {
  const s = new Set(expandedActivityGroups.value)
  if (s.has(groupId)) s.delete(groupId)
  else s.add(groupId)
  expandedActivityGroups.value = s
}

function isActivityGroupExpanded(groupId) {
  return expandedActivityGroups.value.has(groupId)
}

function toolCallHasExpandableContent(actItem) {
  if (getToolCallStatus(actItem) === 'failed') return true
  if (!getToolCallDetails(actItem)) return false
  const kind = getToolCallDetailKind(actItem)
  if (kind === 'json') return devModeRef.value
  return true // code or text
}

// Delegate expand/collapse: auto-expand running delegates once, then let user control
function isDelegateExpanded(itemId) {
  return expandedDelegates.value.has(itemId)
}

function onDelegateToggle(itemId, event) {
  const isOpen = event.target.open
  const s = new Set(expandedDelegates.value)
  if (isOpen) s.add(itemId)
  else s.delete(itemId)
  expandedDelegates.value = s
}

// Auto-expand delegates when they first appear as running
function autoExpandRunningDelegates() {
  let changed = false
  const s = new Set(expandedDelegates.value)
  for (const item of items.value) {
    if (item.item_type === 'tool_call' && item.tool_name === 'delegate' && !autoExpandedDelegates.has(item.id)) {
      const summary = getDelegateActivitySummary(item.id)
      if (summary.isRunning || getChildItems(item.id).length > 0) {
        autoExpandedDelegates.add(item.id)
        s.add(item.id)
        changed = true
      }
    }
  }
  if (changed) expandedDelegates.value = s
}
watch(() => items.value.length, autoExpandRunningDelegates)

// Check if this is the last activity group (failures in non-last groups were self-healed)
function isLastActivityGroup(group) {
  let lastSeen = null
  const seen = new Set()
  for (const g of activityGroupInfo.value.values()) {
    if (!seen.has(g.id)) {
      seen.add(g.id)
      lastSeen = g
    }
  }
  return lastSeen && lastSeen.id === group.id
}

// Track assistant messages whose thinking is absorbed by a preceding activity group
const itemsFollowingActivityGroup = computed(() => {
  const result = new Map() // itemId -> group
  let lastGroup = null

  for (const item of topLevelItems.value) {
    if (activityGroupInfo.value.has(item.id)) {
      lastGroup = activityGroupInfo.value.get(item.id)
    } else if (item.item_type === 'user_message') {
      // User messages break the chain entirely
      lastGroup = null
    } else if (item.item_type === 'assistant_message' && hasThinking(item)) {
      // Assistant message with thinking following an activity group — absorb the thinking
      if (lastGroup) {
        result.set(item.id, lastGroup)
      }
      lastGroup = null
    }
    // Other item types (media_display, progress_display, tool_result, etc.)
    // are output from the activity group and don't break the chain
  }

  return result
})

// Check if any activity group is currently running (to suppress typing indicator)
const hasRunningActivityGroup = computed(() => {
  const seen = new Set()
  for (const group of activityGroupInfo.value.values()) {
    if (seen.has(group.id)) continue
    seen.add(group.id)
    if (getActivityGroupSummaryRaw(group).isRunning) return true
  }
  return false
})

// Core summary logic (without trailing thinking)
function getActivityGroupSummaryRaw(group) {
  const toolNames = []
  let totalThinkingSeconds = 0
  let hasRunningTool = false
  let hasRunningThinking = false

  for (const item of group.items) {
    if (item.item_type === 'tool_call') {
      if (getToolCallStatus(item) === 'running') hasRunningTool = true
      // Skip infrastructure tools from pill summary
      if (HIDDEN_TOOLS.has(item.tool_name)) continue
      const displayName = getToolCallDisplayName(item)
      // Deduplicate consecutive identical names
      if (toolNames.length === 0 || toolNames[toolNames.length - 1] !== displayName) {
        toolNames.push(displayName)
      }
    }
    if (item.item_type === 'assistant_message' && hasThinking(item)) {
      if (isThinkingInProgress(item)) {
        hasRunningThinking = true
      } else {
        const meta = getItemMetadata(item)
        if (meta?.thinking_duration_seconds) totalThinkingSeconds += meta.thinking_duration_seconds
      }
    }
  }

  const isRunning = hasRunningTool || hasRunningThinking
  const toolCalls = group.items.filter(i => i.item_type === 'tool_call')
  const lastToolCall = toolCalls[toolCalls.length - 1]
  const hasFailed = lastToolCall ? getToolCallStatus(lastToolCall) === 'failed' : false

  return { toolNames, totalThinkingSeconds, isRunning, hasFailed, hasRunningTool, hasRunningThinking }
}

function getActivityGroupSummary(group) {
  const raw = getActivityGroupSummaryRaw(group)
  let { toolNames, totalThinkingSeconds, isRunning, hasFailed, hasRunningThinking } = raw

  // Include trailing thinking from assistant messages that follow this group
  for (const [itemId, g] of itemsFollowingActivityGroup.value) {
    if (g.id !== group.id) continue
    const item = items.value.find(i => i.id === itemId)
    if (!item) continue
    if (isThinkingInProgress(item)) {
      hasRunningThinking = true
      isRunning = true
    } else {
      const meta = getItemMetadata(item)
      if (meta?.thinking_duration_seconds) totalThinkingSeconds += meta.thinking_duration_seconds
    }
  }

  let thinkingLabel = ''
  if (hasRunningThinking) {
    thinkingLabel = 'thinking'
  } else if (totalThinkingSeconds > 0) {
    if (totalThinkingSeconds < 60) {
      thinkingLabel = `${totalThinkingSeconds.toFixed(1)}s`
    } else {
      const mins = Math.floor(totalThinkingSeconds / 60)
      const secs = (totalThinkingSeconds % 60).toFixed(0)
      thinkingLabel = `${mins}m ${secs}s`
    }
  }

  return { toolNames, thinkingLabel, isRunning, hasFailed, hasRunningThinking }
}

function getHITLSummary(item) {
  const action = parseHITLAction(item)
  if (!action) return 'HITL request'
  const typeLabels = {
    'approve': 'Approval requested',
    'choose': 'Choice requested',
    'feedback': 'Feedback requested',
    'answer': 'Question asked'
  }
  return typeLabels[action.type] || 'HITL request'
}

function getHITLResponseSummary(item) {
  if (!item.item_metadata) return 'Response submitted'
  try {
    const data = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    const response = data.response || {}
    const actionType = data.action_type

    if (actionType === 'approve') {
      return response.approved ? 'Approved' : 'Rejected'
    }
    if (actionType === 'choose') {
      const count = response.selected_media_ids?.length || 0
      return `Selected ${count} image${count !== 1 ? 's' : ''}`
    }
    if (actionType === 'feedback') {
      const fb = response.item_feedback || {}
      const liked = Object.values(fb).filter(v => v === true).length
      const disliked = Object.values(fb).filter(v => v === false).length
      return `${liked} liked, ${disliked} disliked`
    }
    if (actionType === 'answer') {
      return response.answer || 'Response submitted'
    }
    return 'Response submitted'
  } catch (e) {
    return 'Response submitted'
  }
}

function handleHITLResponded() {
  activeHITLNodeId.value = null
}

async function handleCompareFromSlideshow({ leftMediaId, rightMediaId }) {
  await enterCompare({ leftMediaId, rightMediaId, returnTo: 'slideshow' })
}

// Plan visualization helpers
function hasPlanData(item) {
  if (!item.item_metadata) return false
  try {
    const data = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return data && data.nodes && Array.isArray(data.nodes)
  } catch (e) {
    return false
  }
}

function getPlanData(item) {
  if (!item.item_metadata) return { nodes: [] }
  try {
    const data = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return data || { nodes: [] }
  } catch (e) {
    return { nodes: [] }
  }
}

// Notepad helpers
function hasNotepadData(item) {
  if (!item.item_metadata) return false
  try {
    const data = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return data && data.kind === 'v2_notepad'
  } catch (e) {
    return false
  }
}

function parseNotepadData(item) {
  const fallback = { tasks: [], scratchpad: '' }
  if (!item.item_metadata) return fallback
  try {
    const data = typeof item.item_metadata === 'string'
      ? JSON.parse(item.item_metadata)
      : item.item_metadata
    return {
      tasks: data.tasks || [],
      scratchpad: data.scratchpad || '',
    }
  } catch (e) {
    return fallback
  }
}

// Find the most recent plan item ID
const mostRecentPlanItemId = computed(() => {
  for (let i = items.value.length - 1; i >= 0; i--) {
    const item = items.value[i]
    if (item.item_type === 'system' && hasPlanData(item)) {
      return item.id
    }
  }
  return null
})

// Version key for nodeStates to force PlanVisualization re-renders
const nodeStatesKey = computed(() => {
  const states = nodeStates.value
  return Object.entries(states).map(([id, s]) => `${id}:${s.status}`).join(',')
})

// Track which plan items are expanded (collapsed by default)
const expandedPlanItems = ref(new Set())
function togglePlanExpanded(itemId) {
  if (expandedPlanItems.value.has(itemId)) {
    expandedPlanItems.value.delete(itemId)
  } else {
    expandedPlanItems.value.add(itemId)
  }
}
function isPlanExpanded(itemId) {
  return expandedPlanItems.value.has(itemId)
}

// Get merged execution state: static from plan item + live from websocket
function getMergedExecutionState(item) {
  const planData = getPlanData(item)
  const staticState = planData._execution_state || {}

  // Only merge live nodeStates for the most recent plan
  // Old plans should just show their static/saved state
  const isMostRecent = item.id === mostRecentPlanItemId.value

  if (!isMostRecent) {
    // Old plan - return static state only
    return staticState
  }

  // Most recent plan - merge static with live websocket updates
  const mergedNodeStates = { ...(staticState.node_states || {}) }
  for (const [nodeId, liveState] of Object.entries(nodeStates.value)) {
    mergedNodeStates[nodeId] = liveState
  }

  return {
    ...staticState,
    node_states: mergedNodeStates,
    running_nodes: runningNodes.value
  }
}

// Get plan control button states for a plan item
function getPlanControlState(item) {
  const planData = getPlanData(item)
  const status = planData.status || 'pending'

  // Only the most recent plan can have active controls
  const isMostRecent = item.id === mostRecentPlanItemId.value

  return {
    status,
    // Show cancel only for plans that are actually running (use plan's own status, not agentRunning)
    // This correctly handles: old finished plans, reload scenarios, planning phase
    showCancel: isMostRecent && status === 'running',
    // Show rerun for the most recent plan that's not running (completed, interrupted, or failed)
    showRerun: isMostRecent && status !== 'running' && ['completed', 'interrupted', 'failed'].includes(status),
    // Is this plan currently active?
    isActive: isMostRecent && status === 'running',
  }
}

// All media IDs including trashed (for slideshow) - in order of appearance, deduplicated
const allChatMediaIds = computed(() => {
  const mediaIds = []
  const seen = new Set()

  // Helper to add ID only if not seen before
  const addIfNew = (id) => {
    if (id && !seen.has(id)) {
      seen.add(id)
      mediaIds.push(id)
    }
  }

  // Collect from all item types that contain media (in order they appear)
  for (const item of items.value) {
    // Media display items
    if (item.item_type === 'media_display' && item.item_metadata) {
      try {
        const data = typeof item.item_metadata === 'string'
          ? JSON.parse(item.item_metadata)
          : item.item_metadata
        const displayData = data.display_data || {}
        if (displayData.rows) {
          for (const row of displayData.rows) {
            addIfNew(row.output?.media_id)
          }
        }
      } catch (e) { /* ignore parse errors */ }
    }
    // Progress display previews
    if (item.item_type === 'progress_display' && item.item_metadata) {
      try {
        const data = typeof item.item_metadata === 'string'
          ? JSON.parse(item.item_metadata)
          : item.item_metadata
        for (const mid of (data.display_data?.previews || [])) {
          addIfNew(mid)
        }
      } catch (e) { /* ignore parse errors */ }
    }
  }
  return mediaIds
})
// Non-deleted media IDs only (for strip display and marker loading - avoids 404s and broken images)
const liveChatMediaIds = computed(() => {
  const liveIds = []
  const seen = new Set()

  // Helper to add ID only if not seen before
  const addIfNew = (id) => {
    if (id && !seen.has(id)) {
      seen.add(id)
      liveIds.push(id)
    }
  }

  // Collect from all item types, skipping deleted items
  for (const item of items.value) {
    // Media display items - skip deleted outputs
    if (item.item_type === 'media_display' && item.item_metadata) {
      try {
        const data = typeof item.item_metadata === 'string'
          ? JSON.parse(item.item_metadata)
          : item.item_metadata
        const displayData = data.display_data || {}
        if (displayData.rows) {
          for (const row of displayData.rows) {
            // Only include non-deleted and non-trashed items
            const isDeleted = row.output?.deleted
            const isTrashed = row.output?.status === 'trashed'
            if (row.output?.media_id && !isDeleted && !isTrashed) {
              addIfNew(row.output.media_id)
            }
          }
        }
      } catch (e) { /* ignore parse errors */ }
    }
    // Progress display previews
    if (item.item_type === 'progress_display' && item.item_metadata) {
      try {
        const data = typeof item.item_metadata === 'string'
          ? JSON.parse(item.item_metadata)
          : item.item_metadata
        for (const mid of (data.display_data?.previews || [])) {
          addIfNew(mid)
        }
      } catch (e) { /* ignore parse errors */ }
    }
    // Inline media refs in assistant messages: ![...](media_id=123) or ![...](media:123)
    if (item.item_type === 'assistant_message' && item.message_text) {
      const re = /!\[[^\]]*\]\(media(?:_id=|:)(\d+)\)/g
      let match
      while ((match = re.exec(item.message_text)) !== null) {
        addIfNew(parseInt(match[1], 10))
      }
    }
  }
  return liveIds
})

// Watch for new media IDs and load their markers (only for non-trashed items)
watch(liveChatMediaIds, async (newIds, oldIds) => {
  const oldSet = new Set(oldIds || [])
  const newMediaIds = newIds.filter(id => !oldSet.has(id))

  // Batch load markers for new media items
  if (newMediaIds.length > 0) {
    await loadMediaMarkersBatch(newMediaIds)
  }
}, { immediate: true })

// Status text based on current state
const statusText = computed(() => {
  if (hasActiveHITLRequest.value) {
    return 'Waiting for your input'
  }
  if (agentRunning.value) {
    return 'Agent is processing...'
  }
  if (agentPaused.value) {
    return 'Agent paused - click play to continue'
  }
  return 'Ready'
})

// Delete confirmation message
const deleteConfirmMessage = computed(() => {
  return `Are you sure you want to delete "${chat.value?.name}"? This cannot be undone.`
})


// Load chat details
async function loadChat() {
  loadError.value = false
  try {
    const response = await fetch(`/api/chats/${chatId.value}`)
    if (!response.ok) {
      throw new Error('Failed to load chat')
    }
    chat.value = await response.json()
    await fetchAvailableModels(chat.value?.project_id, true)

    // Sync auto-delete duration: ensure chat's generation_settings has the current profile value
    // This fixes the issue where new chats don't have auto_delete_duration set
    await syncAutoDeleteToChat()

  } catch (error) {
    console.error('Error loading chat:', error)
    loadError.value = true
  }
}

// Sync the profile's auto-delete duration to the chat's generation_settings if not already set
async function syncAutoDeleteToChat() {
  if (!chat.value) return

  const genSettings = chat.value?.generation_settings || {}
  const currentSettings = typeof genSettings === 'string' ? JSON.parse(genSettings) : genSettings

  // Only sync if the chat doesn't already have an auto_delete_duration set
  if (!currentSettings.auto_delete_duration) {
    try {
      const updatedSettings = {
        ...currentSettings,
        auto_delete_duration: CHAT_AUTO_DELETE_DURATION
      }

      const response = await fetch(`/api/chats/${chatId.value}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          generation_settings: JSON.stringify(updatedSettings)
        })
      })

      if (response.ok) {
        const updatedChat = await response.json()
        chat.value = updatedChat
      }
    } catch (error) {
      console.error('Error syncing auto-delete duration to chat:', error)
    }
  }
}

// Sync agent status from backend (recovers from stale frontend state after server restart)
async function syncAgentStatus() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/plan-status`)
    if (!response.ok) return

    const data = await response.json()

    if (!data.has_plan) {
      // No active plan - agent is idle
      agentRunning.value = false
      agentPlanning.value = false
      agentPaused.value = false
      if (data.is_stale) {
        // Server restarted mid-v2-execution — backend cleaned up stale
        // in-progress items, reload to pick up the updated state.
        console.log('[syncAgentStatus] Server restart detected, reloading items')
        await loadItems()
      }
    } else if (data.is_stale) {
      // Plan is stale (server restarted mid-execution) - auto-cancel to recover
      console.log('Detected stale running plan, auto-cancelling to recover')
      await cancelAgent()
    } else {
      // Sync state based on plan status
      switch (data.status) {
        case 'running':
          agentRunning.value = true
          agentPlanning.value = false
          agentPaused.value = false
          break
        case 'paused':
          agentRunning.value = false
          agentPlanning.value = false
          agentPaused.value = true
          break
        case 'pending':
          // Plan exists but hasn't started - treat as planning
          agentRunning.value = false
          agentPlanning.value = true
          agentPaused.value = false
          break
        default:
          // completed, failed, interrupted - agent is idle
          agentRunning.value = false
          agentPlanning.value = false
          agentPaused.value = false
      }
    }
  } catch (error) {
    console.error('Error syncing agent status:', error)
  }
}

// Full reload - both chat metadata and items
async function reloadAll() {
  loading.value = true
  loadError.value = false
  await loadChat()
  if (!loadError.value) {
    await loadItems()
  }
  loading.value = false
}

// Update auto-delete duration - saves to both localStorage (via composable) and chat settings
async function updateAutoDeleteDuration(_duration) {
  const forcedDuration = CHAT_AUTO_DELETE_DURATION

  // Also save to chat's generation_settings for the agent to read
  if (chat.value) {
    try {
      const genSettings = chat.value?.generation_settings || {}
      const currentSettings = typeof genSettings === 'string' ? JSON.parse(genSettings) : genSettings

      const updatedSettings = {
        ...currentSettings,
        auto_delete_duration: forcedDuration
      }

      const response = await fetch(`/api/chats/${chatId.value}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          generation_settings: JSON.stringify(updatedSettings)
        })
      })

      if (response.ok) {
        const updatedChat = await response.json()
        chat.value = updatedChat
      }
    } catch (error) {
      console.error('Error saving auto-delete duration to chat:', error)
    }
  }
}

// Load chat items
async function loadItems(beforeId = null) {
  try {
    let url
    if (beforeId) {
      // Pagination: load older items
      url = `/api/chats/${chatId.value}/items?limit=50&before_id=${beforeId}`
    } else {
      // Initial load: request enough items to have 500 VISIBLE items
      // Backend will keep fetching until it has 500 visible items (filters out tool_call, etc.)
      url = `/api/chats/${chatId.value}/items?visible_limit=500`
    }

    const response = await fetch(url)
    if (!response.ok) {
      throw new Error('Failed to load chat items')
    }

    const data = await response.json()

    // Debug: log loaded items summary
    console.log(`Loaded ${data.items.length} items, hasMore: ${data.has_more}`)

    if (beforeId) {
      // Prepend older messages (API returns newest-first, reverse for display order)
      items.value = [...data.items.reverse(), ...items.value]
    } else {
      // Initial load - API returns newest first, reverse to show oldest-to-newest
      items.value = data.items.reverse()
    }

    hasMore.value = data.has_more
    loading.value = false

    // Initialize message history from existing user messages (on initial load).
    // Strip any baked-in flow-reference headers so arrow-up navigation
    // surfaces the user's pristine text rather than the transport markdown.
    if (!beforeId) {
      const userMessages = data.items
        .filter(item => item.item_type === 'user_message' && item.message_text)
        .map(item => parseMessageReferences(item.message_text).text || item.message_text)
      messageHistory.value = userMessages
    }

    // Scroll to bottom on initial load - use multiple nextTicks to ensure render completes
    if (!beforeId) {
      await nextTick()
      await nextTick()
      scrollToBottom()
      // Also scroll after a short delay as a fallback (images might load)
      setTimeout(scrollToBottom, 100)
    }
  } catch (error) {
    console.error('Error loading chat items:', error)
    loading.value = false
  }
}

// Load more messages
let loadingMore = false
async function loadMore() {
  if (items.value.length === 0 || loadingMore) return
  loadingMore = true

  try {
    // Save scroll position so we can restore it after prepending
    const container = messagesContainer.value
    const scrollHeightBefore = container ? container.scrollHeight : 0

    const oldestId = items.value[0].id
    await loadItems(oldestId)

    // Restore scroll position after prepend
    if (container) {
      await nextTick()
      const scrollHeightAfter = container.scrollHeight
      container.scrollTop += scrollHeightAfter - scrollHeightBefore
    }
  } finally {
    loadingMore = false
  }
}

// Set up IntersectionObserver for infinite scroll
function setupLoadMoreObserver() {
  if (loadMoreObserver.value) {
    loadMoreObserver.value.disconnect()
  }
  if (!loadMoreSentinel.value) return

  loadMoreObserver.value = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && hasMore.value) {
        loadMore()
      }
    },
    { root: messagesContainer.value, rootMargin: '200px 0px 0px 0px' }
  )
  loadMoreObserver.value.observe(loadMoreSentinel.value)
}

// Re-observe when hasMore changes (sentinel appears/disappears)
watch([hasMore, () => loadMoreSentinel.value], () => {
  if (hasMore.value && loadMoreSentinel.value) {
    setupLoadMoreObserver()
  } else if (loadMoreObserver.value) {
    loadMoreObserver.value.disconnect()
  }
})

// Handle Enter key in textarea
function handleEnterKey(event) {
  // Enter without shift sends the message
  sendMessage()
}

// Send "continue" to resume after an app-restart interruption. The banner
// hides automatically once the new user_message lands (chatInterrupted re-
// evaluates and the user_message short-circuits the scan).
function continueAfterInterrupt() {
  messageInput.value = 'continue'
  sendMessage()
}

// Handle up/down arrow keys for message history
function handleKeyDown(event) {
  // ESC while the agent is running stops it — mirrors clicking the Stop button.
  if (event.key === 'Escape' && showStopButton.value) {
    event.preventDefault()
    stopAgent()
    return
  }

  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return

  const textarea = messageInputRef.value
  if (!textarea) return

  if (event.key === 'ArrowUp') {
    // Only navigate history if at start of input or input is empty
    if (textarea.selectionStart === 0 && textarea.selectionEnd === 0) {
      event.preventDefault()
      navigateHistory(1)  // Go back in history
    }
  } else if (event.key === 'ArrowDown') {
    // Only navigate history if at end of input
    const atEnd = textarea.selectionStart === messageInput.value.length
    if (atEnd && historyIndex.value >= 0) {
      event.preventDefault()
      navigateHistory(-1)  // Go forward in history
    }
  }
}

function navigateHistory(direction) {
  if (messageHistory.value.length === 0) return

  const newIndex = historyIndex.value + direction

  // Going up (back in history)
  if (direction > 0) {
    if (newIndex >= messageHistory.value.length) return  // Already at oldest

    // Save current input when first entering history
    if (historyIndex.value === -1) {
      savedCurrentInput.value = messageInput.value
    }

    historyIndex.value = newIndex
    messageInput.value = messageHistory.value[newIndex]
  }
  // Going down (forward in history)
  else {
    if (newIndex < -1) return

    historyIndex.value = newIndex

    if (newIndex === -1) {
      // Restore saved current input
      messageInput.value = savedCurrentInput.value
    } else {
      messageInput.value = messageHistory.value[newIndex]
    }
  }
}

// Queue a message (when agent is busy)
function queueMessage() {
  const hasMessage = messageInput.value.trim()
  const hasAttachments = inputAttachments.value.length > 0

  if (!hasMessage && !hasAttachments) return

  const userMessage = messageInput.value.trim()

  // Add the user-authored message (without refs header) to history so arrow-
  // up navigation shows what the user typed, not the prepended metadata.
  if (userMessage) {
    messageHistory.value.unshift(userMessage)
    if (messageHistory.value.length > 100) {
      messageHistory.value.pop()
    }
  }
  historyIndex.value = -1
  savedCurrentInput.value = ''

  // Build attachments for storage
  const attachments = inputAttachments.value.map(a => ({
    media_id: a.media_id || null,
    path: a.path || null,
    filename: a.filename || null
  }))

  // Fold any attached flow references into the queued message body. The
  // queue runs later via sendMessage(queuedMessage), which reads text as-is
  // — so we need to bake the header in now. Clear refs so they don't leak
  // into the next message the user composes while the queue drains.
  const refsApi = useFlowReferences(chatId.value)
  const refs = [...refsApi.items.value]
  const header = refs.length > 0 ? formatReferencesForMessage(refs) : ''
  const message = header
    ? (userMessage ? `${header}\n\n${userMessage}` : header)
    : userMessage
  if (refs.length > 0) refsApi.clear()

  // Add to queue
  messageQueue.value.push({
    text: message,
    attachments: attachments
  })

  // Clear input
  messageInput.value = ''
  inputAttachments.value = []
}

// Remove a queued message
function removeQueuedMessage(index) {
  messageQueue.value.splice(index, 1)
}

function updateChatModel(slug) {
  if (chat.value) {
    chat.value.model_slug = slug
  }
}

const showModelPicker = computed(() => {
  return !!(chat.value && chatId.value)
})

const noUsableChatModels = computed(() => {
  if (modelsLoading.value) return false
  return availableModels.value.length > 0 && !availableModels.value.some(model => model.available !== false)
})

const showNoModelSetupHero = computed(() => noUsableChatModels.value && !loadError.value && !loading.value)

const selectedChatModel = computed(() => {
  const slug = chat.value?.model_slug || globalDefault.value
  return getResolvedModel(slug) || availableModels.value.find(model => model.slug === slug)
})

const isChatModelUnavailable = computed(() => {
  if (modelsLoading.value) return false
  if (noUsableChatModels.value) return true
  const slug = chat.value?.model_slug || globalDefault.value
  if (availableModels.value.length > 0 && slug && !selectedChatModel.value) return true
  return selectedChatModel.value?.available === false
})

const modelUnavailableMessage = computed(() => {
  if (!isChatModelUnavailable.value) return ''
  const model = selectedChatModel.value
  const slug = chat.value?.model_slug || globalDefault.value
  return model?.description || `The selected model (${slug}) is no longer available. Sign in to Stimma Cloud or configure a local endpoint in Settings > Advanced.`
})

// Send a message (from input or from queue)
async function sendMessage(queuedMessage = null) {
  if (isChatModelUnavailable.value) {
    addToast({ type: 'error', message: modelUnavailableMessage.value })
    // A dequeued message must survive the early return — put it back.
    if (queuedMessage) messageQueue.value.unshift(queuedMessage)
    return
  }

  const refsApi = useFlowReferences(chatId.value)
  let message, attachments

  if (queuedMessage) {
    // Sending from queue — reference header was already baked in at queue
    // time, so nothing to do here.
    message = queuedMessage.text
    attachments = queuedMessage.attachments || []
  } else {
    // Sending from input
    const hasMessage = messageInput.value.trim()
    const hasAttachments = inputAttachments.value.length > 0

    if (!hasMessage && !hasAttachments) return

    // If agent is busy or we're already sending, queue instead
    if (((agentRunning.value || agentPlanning.value) && !hasActiveHITLRequest.value) || sending.value) {
      queueMessage()
      return
    }

    message = messageInput.value.trim()

    // Add to history (at the front, most recent first) — stores the user-
    // authored text only, so arrow-up navigation doesn't replay the ref
    // header as if the user had typed it.
    if (message) {
      messageHistory.value.unshift(message)
      // Keep history to a reasonable size
      if (messageHistory.value.length > 100) {
        messageHistory.value.pop()
      }
    }
    // Reset history navigation state
    historyIndex.value = -1
    savedCurrentInput.value = ''

    // Bake any pending flow references into the outgoing message body.
    // The agent sees them as a blockquote header above the user's message.
    const refs = [...refsApi.items.value]
    if (refs.length > 0) {
      const header = formatReferencesForMessage(refs)
      message = message ? `${header}\n\n${message}` : header
    }

    // Build attachments array for the backend
    attachments = inputAttachments.value.map(a => ({
      media_id: a.media_id || null,
      path: a.path || null,
      filename: a.filename || null
    }))
  }

  if (hasActiveHITLRequest.value) {
    const interrupted = await interruptPendingHITLRequest()
    if (!interrupted) {
      if (queuedMessage) messageQueue.value.unshift(queuedMessage)
      return
    }
  }

  // Collect attachment media IDs for selected_media_ids
  const attachmentMediaIds = attachments
    .filter(a => a.media_id)
    .map(a => a.media_id)

  // Clear input immediately (only if not from queue)
  let clearedAttachments = []
  let clearedRefs = []
  if (!queuedMessage) {
    messageInput.value = ''
    clearedAttachments = [...inputAttachments.value]
    inputAttachments.value = []
    clearedRefs = [...refsApi.items.value]
    if (clearedRefs.length > 0) refsApi.clear()
    // Reset textarea height after clearing
    nextTick(() => {
      if (messageInputRef.value) {
        messageInputRef.value.style.height = 'auto'
      }
      if (textareaScrollRef.value) {
        textareaScrollRef.value.scrollTop = 0
      }
    })
  }
  sending.value = true

  // Clear post-stop suppression — user is starting a new interaction,
  // so any late-arriving items from the old run should no longer be suppressed.
  suppressingPostStop.value = false

  // Mark agent as running BEFORE the request to avoid race condition
  // (agent might finish before the fetch response arrives)
  agentRunning.value = true
  lastSendStartedAt = Date.now()

  // Once the POST is accepted the message is committed (the user_message is
  // created server-side and arrives over WebSocket). Past this point a failure
  // in post-send work (json parse, scroll) must NOT restore the composer —
  // otherwise the just-sent attachments resuscitate in the input.
  let sent = false
  try {
    // Combine selected_media_ids and attachment media IDs
    const allSelectedIds = [
      ...(selectedMediaIds.value.length > 0 ? selectedMediaIds.value : []),
      ...attachmentMediaIds
    ]

    const response = await fetch(`/api/chats/${chatId.value}/items`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        item_type: 'user_message',
        message_text: message,
        // Selected media IDs are passed to the agent for "that one" / "the third one" references
        selected_media_ids: allSelectedIds.length > 0 ? allSelectedIds : null,
        // Attachments include both library items and uploaded files
        attachments: attachments.length > 0 ? attachments : null
      })
    })

    if (!response.ok) {
      throw new Error('Failed to send message')
    }
    sent = true

    await response.json()
    // Don't add locally - WebSocket will broadcast it

    await nextTick()
    scrollToBottom()
  } catch (error) {
    console.error('Error sending message:', error)
    if (!sent) {
      // The POST never committed, so no agent run is coming — roll back the
      // optimistic running flag, otherwise the composer and queue deadlock
      // waiting for an agent_stopped that will never arrive.
      agentRunning.value = false
      // A dequeued message that failed to send goes back to the queue front
      // (visible, retried by the queue watchdog) instead of vanishing. The
      // backoff keeps the idle-watcher from retrying in a tight loop while
      // the backend is unreachable.
      if (queuedMessage) {
        messageQueue.value.unshift(queuedMessage)
        queueBackoffUntil = Date.now() + 5000
      }
    }
    // Restore attachments and refs only when the send itself failed (so the
    // user can retry without re-attaching). If the message already committed,
    // leave the composer cleared — restoring would bring sent attachments back.
    if (!queuedMessage && !sent) {
      inputAttachments.value = clearedAttachments
      for (const r of clearedRefs) refsApi.add(r)
    }
  } finally {
    sending.value = false
  }
}

// Process the next queued message when idle
function processNextQueuedMessage() {
  if (sending.value || agentRunning.value || agentPlanning.value) return
  if (messageQueue.value.length === 0) return
  if (Date.now() < queueBackoffUntil) return

  const next = messageQueue.value.shift()
  sendMessage(next)
}

// Watch for idle state to process queue
watch(
  [() => agentRunning.value, () => sending.value, () => agentPlanning.value],
  ([running, isSending, planning]) => {
    if (!running && !isSending && !planning) {
      processNextQueuedMessage()
    }
  }
)

// Queue watchdog: while messages are queued, periodically reconcile agent
// state with the server and try to drain. The idle-watcher above only fires
// on local state *changes* — if agentRunning is stale-true (a missed
// agent_stopped over WebSocket, a send that never started a run), nothing
// ever changes and the queue would sit "queued" forever. The watchdog asks
// the backend for the truth (syncAgentStatus) and retries the drain.
watch(() => messageQueue.value.length, (len) => {
  if (len > 0 && !queueWatchdogTimer) {
    queueWatchdogTimer = setInterval(async () => {
      if (messageQueue.value.length === 0) {
        clearInterval(queueWatchdogTimer)
        queueWatchdogTimer = null
        return
      }
      // Grace period after a send: the backend registers the run a moment
      // after the POST returns, and plan-status would briefly report idle —
      // reconciling in that window would double-send.
      if (Date.now() - lastSendStartedAt < 8000) return
      if (sending.value) return
      await syncAgentStatus()
      processNextQueuedMessage()
    }, 5000)
  } else if (len === 0 && queueWatchdogTimer) {
    clearInterval(queueWatchdogTimer)
    queueWatchdogTimer = null
  }
})


// ===== Input Attachments & Drag/Drop =====

function removeAttachment(index) {
  inputAttachments.value.splice(index, 1)
}

function addAttachmentFromMediaId(mediaId) {
  // Check if already attached
  if (inputAttachments.value.some(a => a.media_id === mediaId)) {
    return
  }
  inputAttachments.value.push({ media_id: mediaId })
}

// ===== Image Strip =====

function openStripSlideshow(mediaId) {
  // Open slideshow at this media ID using all chat media
  openSlideshow(mediaId, 0)
}

function handleStripDragStart(mediaId) {
  // No-op for now, the strip component handles the drag
}

// View media in browse view
function viewMedia(mediaId) {
  // TODO: Open media detail view or navigate to browse with filter
  router.push(`/browse?media=${mediaId}`)
}

function handleImageError(mediaId) {
  console.error(`Failed to load thumbnail for media_id ${mediaId}`)
  // Could add retry logic or fallback image here
}

// Job info/error modal handlers
function showJobInfo(job) {
  selectedJob.value = job
  showJobInfoModal.value = true
}

async function showJobInfoById(jobId) {
  try {
    const response = await fetch(`/api/generate/jobs/${jobId}`, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      const job = await response.json()
      showJobInfo(job)
    } else {
      console.error('Failed to fetch job:', await response.text())
    }
  } catch (error) {
    console.error('Error fetching job:', error)
  }
}

function showJobError(job) {
  selectedJob.value = job
  showJobErrorModal.value = true
}

function closeJobModals() {
  showJobInfoModal.value = false
  showJobErrorModal.value = false
  selectedJob.value = null
}

async function retryJob(jobId) {
  try {
    const response = await fetch(`/api/generate/jobs/${jobId}/retry`, {
      method: 'POST',
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      closeJobModals()
      // The job status will be updated on next poll - grids will show loading state
    } else {
      console.error('Failed to retry job:', await response.text())
    }
  } catch (error) {
    console.error('Error retrying job:', error)
  }
}

function dismissJob(jobId) {
  // Just close the modal - the job stays failed but we don't show it anymore
  closeJobModals()
}

// Load available markers
async function loadMarkers() {
  try {
    const response = await fetch('/api/markers', {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      availableMarkers.value = await response.json()
    }
  } catch (error) {
    console.error('Error loading markers:', error)
  }
}

// Load markers for multiple media items in one request
async function loadMediaMarkersBatch(mediaIds) {
  if (!mediaIds || mediaIds.length === 0) return

  try {
    const response = await fetch('/api/media/markers/batch-get', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      },
      body: JSON.stringify(mediaIds)
    })
    if (response.ok) {
      const markersByMedia = await response.json()
      mediaMarkers.value = {
        ...mediaMarkers.value,
        ...markersByMedia
      }
    }
  } catch (error) {
    console.error('Error loading media markers:', error)
  }
}

// Handle marker toggle
async function handleToggleMarker({ mediaId, marker }) {
  const currentMarkers = mediaMarkers.value[mediaId] || []
  const hasMarker = currentMarkers.some(m => m.id === marker.id)

  try {
    if (hasMarker) {
      // Remove marker
      const response = await fetch(`/api/media/${mediaId}/markers/${marker.id}`, {
        method: 'DELETE',
        headers: { 'X-Profile-ID': getCurrentProfileId() }
      })
      if (response.ok) {
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: currentMarkers.filter(m => m.id !== marker.id)
        }
      }
    } else {
      // Add marker
      const response = await fetch(`/api/media/${mediaId}/markers/${marker.id}`, {
        method: 'POST',
        headers: { 'X-Profile-ID': getCurrentProfileId() }
      })
      if (response.ok) {
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: [...currentMarkers, marker]
        }
      }
    }
  } catch (error) {
    console.error('Error toggling marker:', error)
  }
}

// Thinking helpers - thinking is stored in assistant message metadata
function getItemMetadata(item) {
  if (!item || !item.item_metadata) return null
  return typeof item.item_metadata === 'string' ? JSON.parse(item.item_metadata) : item.item_metadata
}

function hasThinking(item) {
  const meta = getItemMetadata(item)
  // Check metadata first, then check for raw think tags in message (streaming)
  if (meta && (meta.thinking_status || meta.thinking_content)) return true
  return isStreamingThink(item)
}

function isThinkingInProgress(item) {
  const meta = getItemMetadata(item)
  if (meta && meta.thinking_status === 'in_progress') return true
  // Also in progress if we see raw think tags (streaming, not yet parsed)
  return isStreamingThink(item)
}

function isThinkingInterrupted(item) {
  const meta = getItemMetadata(item)
  return meta && meta.thinking_status === 'failed' && meta.thinking_duration_seconds === 0
}

// Check if message contains raw <think> tags (during streaming, before backend parses them)
function isStreamingThink(item) {
  if (!item?.message_text) return false
  const text = item.message_text.toLowerCase()
  // Has opening tag but no closing tag, or has both (still streaming)
  return text.includes('<think>') || text.includes('<thinking>')
}

// Get displayable message text, stripping any raw think tags
function getDisplayText(item) {
  if (!item?.message_text) return null
  let text = item.message_text

  // Strip think/thinking tags and their content (handles partial/complete tags)
  // Pattern: from <think> or <thinking> to </think> or </thinking> or end of string
  text = text.replace(/<think(?:ing)?>([\s\S]*?)(<\/think(?:ing)?>|$)/gi, '')

  // Also strip any orphaned opening tags at the end (partial streaming)
  text = text.replace(/<think(?:ing)?>[\s\S]*$/gi, '')

  return text.trim() || null
}

function isStopEvent(item) {
  const meta = getItemMetadata(item)
  return meta && meta.stop_event
}

function getMessageAttachments(item) {
  const meta = getItemMetadata(item)
  if (!meta || !meta.attachments) return []
  return meta.attachments
}

// Cached parse of a user_message's flow-reference header, so the chip row
// and the remaining-text block don't redo the regex scan three times per
// render. Keyed by item id + message_text so edits invalidate.
const parsedMessageCache = new Map<string, { refs: FlowReference[]; text: string }>()
function parsedUserMessage(item: any): { refs: FlowReference[]; text: string } {
  const key = `${item?.id ?? ''}:${(item?.message_text ?? '').length}`
  let cached = parsedMessageCache.get(key)
  if (!cached || parsedMessageCache.size > 1000) {
    if (parsedMessageCache.size > 1000) parsedMessageCache.clear()
    cached = parseMessageReferences(item?.message_text)
    parsedMessageCache.set(key, cached)
  }
  return cached
}
function getMessageRefs(item: any): FlowReference[] {
  return parsedUserMessage(item).refs
}
function getMessageBodyText(item: any): string {
  return parsedUserMessage(item).text
}

// Queued messages carry already-baked-in reference headers (queueMessage folds
// them in at queue time so the post-dequeue send reads them verbatim). Parse
// the same way so the queued preview shows chips instead of raw markdown.
function parseQueuedRefs(text: string | null | undefined): FlowReference[] {
  return parseMessageReferences(text).refs
}
function stripQueuedRefs(text: string | null | undefined): string {
  return parseMessageReferences(text).text
}

// Check if a media ID is broken/deleted
function isMediaBroken(mediaId: number): boolean {
  return brokenMediaIds.value.has(mediaId)
}

// Handle media image load error (e.g., 404 for deleted media)
function handleMediaLoadError(mediaId: number) {
  brokenMediaIds.value = new Set([...brokenMediaIds.value, mediaId])
}

// Open the generation/image details popup for an attached library item
function openMediaDetails(mediaId: number) {
  if (!mediaId || isMediaBroken(mediaId)) return
  mediaDetailsModal.open(mediaId)
}

function getAttachmentThumbnail(attachment) {
  // If attachment has a media_id, use the media thumbnail
  if (attachment.media_id) {
    return getThumbnailUrl(attachment.media_id, 128)
  }
  // If attachment has a path (uploaded file), use the reference-file endpoint
  if (attachment.path) {
    const profileId = getCurrentProfileId()
    const pin = getCachedPin(profileId)
    let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(attachment.path)}&profile=${encodeURIComponent(profileId)}`
    if (pin) url += `&pin=${encodeURIComponent(pin)}`
    return url
  }
  return ''
}

function getThinkingDuration(item) {
  const meta = getItemMetadata(item)
  if (!meta || meta.thinking_duration_seconds === undefined) return '?s'

  const secs = meta.thinking_duration_seconds
  if (secs < 60) {
    return `${secs.toFixed(1)}s`
  } else {
    const mins = Math.floor(secs / 60)
    const remainingSecs = (secs % 60).toFixed(0)
    return `${mins}m ${remainingSecs}s`
  }
}

function getThinkingContent(item) {
  const meta = getItemMetadata(item)
  return meta ? meta.thinking_content : null
}

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function tokenClass(kind) {
  const theme = document.documentElement.getAttribute('data-theme') || 'dark'
  if (theme === 'light') {
    if (kind === 'string') return 'text-emerald-700'
    if (kind === 'keyword') return 'text-blue-700'
    if (kind === 'number') return 'text-amber-700'
    if (kind === 'comment') return 'text-zinc-500'
    if (kind === 'variable') return 'text-fuchsia-700'
    return 'text-zinc-400'
  }
  if (kind === 'string') return 'text-emerald-300'
  if (kind === 'keyword') return 'text-blue-300'
  if (kind === 'number') return 'text-amber-300'
  if (kind === 'comment') return 'text-zinc-500'
  if (kind === 'variable') return 'text-fuchsia-300'
  return 'text-zinc-600'
}

function highlightPython(code) {
  return code
    .replace(/(&quot;&quot;&quot;[\s\S]*?&quot;&quot;&quot;|&#39;&#39;&#39;[\s\S]*?&#39;&#39;&#39;|&quot;(?:\\.|[^&])*?&quot;|&#39;(?:\\.|[^&])*?&#39;)/g, `<span class="${tokenClass('string')}">$1</span>`)
    .replace(/(^|\s)(from|import|def|class|return|if|elif|else|for|while|try|except|finally|with|as|await|async|yield|lambda|pass|break|continue|in|is|not|and|or|True|False|None)(?=\s|:|\(|$)/gm, `$1<span class="${tokenClass('keyword')}">$2</span>`)
    .replace(/(^|\s)(\d+(?:\.\d+)?)(?=\s|,|\)|\]|$)/gm, `$1<span class="${tokenClass('number')}">$2</span>`)
    .replace(/(#.*)$/gm, `<span class="${tokenClass('comment')}">$1</span>`)
}

function highlightShell(code) {
  return code
    .replace(/(&quot;(?:\\.|[^&])*?&quot;|&#39;(?:\\.|[^&])*?&#39;)/g, `<span class="${tokenClass('string')}">$1</span>`)
    .replace(/(^|\s)(if|then|else|fi|for|do|done|while|case|esac|function|export|local|sudo)(?=\s|$)/gm, `$1<span class="${tokenClass('keyword')}">$2</span>`)
    .replace(/(\$\w+|\$\{[^}]+\})/g, `<span class="${tokenClass('variable')}">$1</span>`)
    .replace(/(#.*)$/gm, `<span class="${tokenClass('comment')}">$1</span>`)
}

function highlightHtml(code) {
  return code
    // HTML comments
    .replace(/(&lt;!--[\s\S]*?--&gt;)/g, `<span class="${tokenClass('comment')}">$1</span>`)
    // Tags and attributes
    .replace(/(&lt;\/?)([\w-]+)((?:\s+[\w-]+(?:=(?:&quot;[^&]*?&quot;|&#39;[^&]*?&#39;|\S+))?)*\s*\/?)(&gt;)/g, (_, open, tag, attrs, close) => {
      let highlighted = `<span class="${tokenClass('keyword')}">${open}${tag}</span>`
      if (attrs) {
        highlighted += attrs.replace(/([\w-]+)(=)(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g,
          `<span class="${tokenClass('variable')}">$1</span>$2<span class="${tokenClass('string')}">$3</span>`)
      }
      highlighted += `<span class="${tokenClass('keyword')}">${close}</span>`
      return highlighted
    })
}

function renderHighlightedCode(code, language = 'text') {
  const lines = escapeHtml(code)
    .split('\n')
    .map((line, index) => {
      const highlighted = language === 'python' ? highlightPython(line) : language === 'bash' ? highlightShell(line) : language === 'html' ? highlightHtml(line) : line
      return `<div class="grid grid-cols-[auto_1fr] gap-4"><span class="select-none text-right text-xs leading-6 min-w-6 ${tokenClass('lineNumber')}">${index + 1}</span><span class="whitespace-pre">${highlighted || '&nbsp;'}</span></div>`
    })
  return lines.join('')
}

// Render markdown to HTML, with media placeholders for inline media references
const MEDIA_PLACEHOLDER_PREFIX = '<!--STIMMA_MEDIA:'
const MEDIA_PLACEHOLDER_SUFFIX = '-->'
const MEDIA_PLACEHOLDER_RE = /<!--STIMMA_MEDIA:(\d+)-->/g

function parseMediaIdFromHref(href) {
  if (!href) return null
  let m = href.match(/^media_id=(\d+)$/)
  if (m) return parseInt(m[1], 10)
  m = href.match(/^media:(\d+)$/)
  if (m) return parseInt(m[1], 10)
  return null
}

function renderMarkdown(text) {
  if (!text) return ''
  const renderer = new marked.Renderer()
  renderer.code = (token) => {
    const code = typeof token === 'string' ? token : (token?.text || '')
    const lang = typeof token === 'string' ? '' : (token?.lang || '')
    const language = (lang || '').toLowerCase()
    const normalized = language === 'py' ? 'python' : language === 'sh' ? 'bash' : language
    const highlighted = renderHighlightedCode(code, normalized)
    return `<div class="rounded-xl border border-white/10 bg-black/20 p-3 overflow-x-auto my-3"><pre class="text-sm leading-6"><code>${highlighted}</code></pre></div>`
  }
  renderer.image = (token) => {
    const href = typeof token === 'string' ? token : (token?.href || '')
    const alt = typeof token === 'string' ? '' : (token?.text || token?.title || '')
    const mediaId = parseMediaIdFromHref(href)
    if (mediaId) {
      return `${MEDIA_PLACEHOLDER_PREFIX}${mediaId}${MEDIA_PLACEHOLDER_SUFFIX}`
    }
    return `<img src="${escapeHtmlAttribute(href)}" alt="${escapeHtmlAttribute(alt)}" />`
  }
  return sanitizeHtml(marked.parse(text, { breaks: true, async: false, renderer }))
}

// Split rendered markdown into segments of html and media references
function parseMarkdownSegments(text) {
  if (!text) return [{ type: 'html', content: '' }]
  const html = renderMarkdown(text)
  const segments = []
  let lastIndex = 0
  let match
  MEDIA_PLACEHOLDER_RE.lastIndex = 0
  while ((match = MEDIA_PLACEHOLDER_RE.exec(html)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'html', content: html.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'media', mediaId: parseInt(match[1], 10) })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < html.length) {
    segments.push({ type: 'html', content: html.slice(lastIndex) })
  }
  return segments.length ? segments : [{ type: 'html', content: html }]
}

// Open slideshow at a specific media ID
function openSlideshow(mediaId, indexInGrid) {
  if (liveChatMediaIds.value.length === 0) return

  // Find the index of this media ID - open immediately without validation
  const index = liveChatMediaIds.value.indexOf(mediaId)
  const startIndex = index !== -1 ? index : 0

  // Create a page provider that references the reactive liveChatMediaIds
  // This way new images will be included as they complete
  const chatPageProvider = async (pageNumber, pageSize) => {
    const allIds = liveChatMediaIds.value  // Get current value at fetch time
    const start = pageNumber * pageSize
    const end = Math.min(start + pageSize, allIds.length)
    const pageIds = allIds.slice(start, end)

    // Fetch all items for this page in parallel (include trashed items)
    const itemPromises = pageIds.map(async (id) => {
      try {
        return await getMediaItem(id, { includeTrashed: true })
      } catch (error) {
        // Return a placeholder for truly deleted items
        return {
          id: id,
          file_hash: null,
          _placeholder: true
        }
      }
    })
    return await Promise.all(itemPromises)
  }

  enterSlideshow({
    totalCount: liveChatMediaIds.value.length,
    startIndex,
    pageProvider: chatPageProvider,
    randomized: false,
    randomSeed: null
  })
}

// Open slideshow for a single reference image (e.g., from edit/i2v input)
async function openSingleImageSlideshow(mediaId) {
  // Create a page provider that returns just this one image
  const singleImageProvider = async (pageNumber, pageSize) => {
    if (pageNumber > 0) return []  // Only one page
    try {
      const item = await getMediaItem(mediaId, { includeTrashed: true })
      return [item]
    } catch (error) {
      return [{
        id: mediaId,
        file_hash: null,
        _placeholder: true
      }]
    }
  }

  enterSlideshow({
    totalCount: 1,
    startIndex: 0,
    pageProvider: singleImageProvider,
    randomized: false,
    randomSeed: null
  })
}

function isLLMSetupError(item) {
  return LLM_SETUP_ERROR_TYPES.has(item?.item_metadata?.error_type)
}

function getRawErrorDetails(item) {
  return item?.item_metadata?.raw_error || item?.message_text || ''
}

function isLastChatItem(item) {
  return items.value.length > 0 && items.value[items.value.length - 1]?.id === item?.id
}

async function retryAfterError() {
  if (agentRunning.value || agentPlanning.value || sending.value) return
  // Optimistically remove the trailing error item(s) — the retry should
  // leave no residue from a transient failure. The backend deletes them
  // too and broadcasts chat_item_deleted, so this just avoids a flash.
  const removed = []
  while (items.value.length > 0 && items.value[items.value.length - 1].item_type === 'error') {
    removed.unshift(items.value.pop())
  }
  try {
    const response = await fetch(`/api/chats/${chatId.value}/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    if (!response.ok) {
      console.error('Failed to retry:', await response.text())
      // Retry never started — put the error items back so the user
      // still sees what happened and can try again.
      items.value = [...items.value, ...removed]
      return
    }
    // agent_started arrives over WebSocket; set optimistically so the
    // composer flips to the stop button without a gap.
    agentRunning.value = true
    lastSendStartedAt = Date.now()
  } catch (error) {
    console.error('Error retrying:', error)
    items.value = [...items.value, ...removed]
  }
}

// Remove all LLM setup error items (after successful sign-in or endpoint config)
async function clearLLMNotConfiguredErrors() {
  const errorItems = items.value.filter(
    item => item.item_type === 'error' && isLLMSetupError(item)
  )
  if (errorItems.length === 0) return
  const errorIds = new Set(errorItems.map(i => i.id))
  items.value = items.value.filter(item => !errorIds.has(item.id))
  await Promise.allSettled(
    errorItems.map(item => fetch(`/api/chats/items/${item.id}`, { method: 'DELETE' }))
  )
}

// Delete a chat item (hard delete)
async function deleteItem(itemId) {
  try {
    const response = await fetch(`/api/chats/items/${itemId}`, {
      method: 'DELETE'
    })

    if (response.ok) {
      // Remove from local items list
      items.value = items.value.filter(item => item.id !== itemId)
    } else {
      console.error('Failed to delete item:', await response.text())
    }
  } catch (error) {
    console.error('Error deleting item:', error)
  }
}

// Delete an item and all items after it
async function deleteFromHere(itemId) {
  const index = items.value.findIndex(item => item.id === itemId)
  if (index === -1) return

  const itemsToDelete = items.value.slice(index)

  // Optimistically remove from local items list immediately to avoid race
  // conditions where WebSocket events (e.g. chat_item_created from a running
  // agent) push new items during the await, causing the old items to remain visible.
  items.value = items.value.slice(0, index)

  // Delete all items on the backend in parallel
  const deletePromises = itemsToDelete.map(item =>
    fetch(`/api/chats/items/${item.id}`, { method: 'DELETE' })
  )

  try {
    await Promise.all(deletePromises)
  } catch (error) {
    console.error('Error deleting items:', error)
  }
}

// Handle media trashed (soft-delete) - mark status as trashed so strip filters it out
function handleMediaTrashed(mediaId: number) {
  for (const item of items.value) {
    if (item.item_type === 'media_display' && item.item_metadata?.display_data?.rows) {
      for (const row of item.item_metadata.display_data.rows) {
        if (row.output?.media_id === mediaId) {
          row.output.status = 'trashed'
        }
      }
    }
  }
}

// Handle media permanent delete - mark as broken so placeholder shows
function handleMediaPermanentDelete(mediaId: number) {
  // Add to broken set so template shows placeholder instead of trying to load
  brokenMediaIds.value = new Set([...brokenMediaIds.value, mediaId])

  // Also remove from mediaMarkers cache
  if (mediaMarkers.value[mediaId]) {
    const { [mediaId]: _, ...rest } = mediaMarkers.value
    mediaMarkers.value = rest
  }

  // Mark deleted in item data so OutputImage shows placeholder
  for (const item of items.value) {
    if (item.item_type === 'media_display' && item.item_metadata?.display_data?.rows) {
      for (const row of item.item_metadata.display_data.rows) {
        if (row.output?.media_id === mediaId) {
          row.output.deleted = true
        }
      }
    }
    // Also check attachments
    if (item.item_metadata?.attachments) {
      for (const attachment of item.item_metadata.attachments) {
        if (attachment.media_id === mediaId) {
          attachment.deleted = true
        }
      }
    }
  }
}

// Delete from here and resend the message
async function replayFromHere(item) {
  if (item.item_type !== 'user_message' || !item.message_text) return

  const parsed = parseMessageReferences(item.message_text)
  const message = parsed.refs.length > 0 ? parsed.text : item.message_text
  // Copy — getMessageAttachments returns the stored item's metadata array by
  // reference, and we must not alias it into the composer (composer edits would
  // mutate the historical message in place).
  const attachments = getMessageAttachments(item).map(a => ({ ...a }))

  // Abort any running agent BEFORE deleting and resending. Without this the
  // resend lands in the client-side queue behind a run whose completion event
  // may never arrive (or that we're about to orphan by deleting its items),
  // leaving the message stuck "queued" forever.
  await cancelAgent()

  // Delete this item and all items after it
  await deleteFromHere(item.id)

  // Set the message input and attachments, then send
  messageInput.value = message
  inputAttachments.value = attachments
  await nextTick()
  await sendMessage()
}

// Start editing a user message inline
function startEditing(item) {
  if (item.item_type !== 'user_message' || !item.message_text) return

  // Capture original bubble size before switching to edit mode
  const bubble = document.querySelector(`[data-item-id="${item.id}"] .bg-blue-600`)
  if (bubble) {
    const rect = bubble.getBoundingClientRect()
    editingMinSize.value = { width: Math.max(200, rect.width), height: Math.max(60, rect.height) }
  } else {
    editingMinSize.value = { width: 200, height: 60 }
  }

  editingItemId.value = item.id
  // Strip the flow-reference header before showing the editor — the user
  // edits their own text only. The references were transport metadata, not
  // content; re-attaching would be done via the composer, not the editor.
  editingText.value = parseMessageReferences(item.message_text).text || item.message_text
  nextTick(() => {
    // Find the textarea by data attribute (more reliable than ref in v-for)
    const textarea = document.querySelector('[data-edit-input]')
    if (textarea) {
      textarea.focus()
      textarea.select()
      // Size to fit initial content (may grow beyond min size)
      autoResizeEditTextarea({ target: textarea })
    }
  })
}

// Cancel editing
function cancelEditing() {
  editingItemId.value = null
  editingText.value = ''
}

// Auto-resize edit textarea to fit content
function autoResizeEditTextarea(event) {
  const textarea = event?.target || document.querySelector('[data-edit-input]')
  if (!textarea) return
  // Reset height to auto to get proper scrollHeight
  textarea.style.height = 'auto'
  // Set to scrollHeight (respecting captured min height)
  const minH = editingMinSize.value.height || 60
  textarea.style.height = Math.max(minH, textarea.scrollHeight) + 'px'
}

// Submit the edited message - deletes from here and resends with new text
async function submitEditedMessage(item) {
  if (!editingText.value.trim()) {
    cancelEditing()
    return
  }

  const newMessage = editingText.value
  // Copy — see replayFromHere: don't alias the stored message's metadata array.
  const attachments = getMessageAttachments(item).map(a => ({ ...a }))

  // Clear editing state
  cancelEditing()

  // Abort any running agent first — see replayFromHere for why.
  await cancelAgent()

  // Delete this item and all items after it
  await deleteFromHere(item.id)

  // Set the message input and attachments, then send
  messageInput.value = newMessage
  inputAttachments.value = attachments
  await nextTick()
  await sendMessage()
}

// Handle keydown in edit input
function handleEditKeydown(event, item) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submitEditedMessage(item)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    cancelEditing()
  }
}

// Copy JSON from this item onwards to clipboard (compact, one per line)
async function copyJsonFromHere(itemId) {
  const index = items.value.findIndex(item => item.id === itemId)
  if (index === -1) return

  const itemsToCopy = items.value.slice(index)
  // Compact JSON: one item per line, strip nulls
  const lines = itemsToCopy.map(item => JSON.stringify(stripNulls(item)))
  const text = lines.join('\n')

  const success = await copyToClipboard(text)
  if (success) {
    addToast(`Copied ${itemsToCopy.length} item${itemsToCopy.length !== 1 ? 's' : ''} to clipboard`, 'success', 2000)
  } else {
    addToast('Failed to copy to clipboard', 'error', 3000)
  }
}

// Copy subagent child items to clipboard
async function copyChildItems(parentItemId) {
  const children = getChildItems(parentItemId)
  if (!children.length) return
  const lines = children.map(item => JSON.stringify(stripNulls(item)))
  const text = lines.join('\n')
  const success = await copyToClipboard(text)
  if (success) {
    addToast(`Copied ${children.length} subagent item${children.length !== 1 ? 's' : ''} to clipboard`, 'success', 2000)
  } else {
    addToast('Failed to copy to clipboard', 'error', 3000)
  }
}

// Rename chat (called from control strip)
async function renameChatFromStrip(newName) {
  try {
    const response = await fetch(`/api/chats/${chatId.value}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: newName
      })
    })

    if (response.ok) {
      const updatedChat = await response.json()
      chat.value = updatedChat
    }
  } catch (error) {
    console.error('Error renaming chat:', error)
  }
}

// Delete chat
function confirmDelete() {
  showDeleteModal.value = true
}

async function deleteChat() {
  showDeleteModal.value = false

  const id = chatId.value
  if (id == null) return
  const projectId = chat.value?.project_id

  try {
    const response = await fetch(`/api/chats/${id}`, { method: 'DELETE' })
    if (!response.ok) throw new Error('delete failed')
  } catch (error) {
    console.error('Error deleting chat:', error)
    addToast('Failed to delete chat', 'error', 5000)
    return
  }

  if (projectId) {
    router.push({ name: 'project-chats', params: { id: projectId } })
  } else {
    router.push({ name: 'chats' })
  }

  addToast('Deleted 1 chat', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      try {
        const response = await fetch(`/api/chats/${id}/restore`, { method: 'POST' })
        if (!response.ok) throw new Error('restore failed')
      } catch (error) {
        console.error('Error restoring chat:', error)
        addToast('Failed to restore chat', 'error', 5000)
      }
    }
  })
}

async function cloneChat() {
  try {
    console.log('Cloning chat:', chatId.value)
    const response = await fetch(`/api/chats/${chatId.value}/clone`, {
      method: 'POST'
    })

    console.log('Clone response status:', response.status)
    if (response.ok) {
      const newChat = await response.json()
      console.log('Cloned chat:', newChat)
      // Navigate to the cloned chat
      router.push({ name: 'chat', params: { id: newChat.id } })
    } else {
      const errorText = await response.text()
      console.error('Clone failed:', response.status, errorText)
    }
  } catch (error) {
    console.error('Error cloning chat:', error)
  }
}

async function branchFromHere(itemId) {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/branch?from_chatitem_id=${itemId}`, {
      method: 'POST'
    })

    if (response.ok) {
      const newChat = await response.json()
      router.push({ name: 'chat', params: { id: newChat.id } })
    } else {
      const errorText = await response.text()
      console.error('Branch failed:', response.status, errorText)
      addToast('Failed to branch chat', 'error', 5000)
    }
  } catch (error) {
    console.error('Error branching chat:', error)
    addToast('Failed to branch chat', 'error', 5000)
  }
}

async function clearChat() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/clear`, {
      method: 'POST'
    })

    if (response.ok) {
      // Clear local items array
      items.value = []
    }
  } catch (error) {
    console.error('Error clearing chat:', error)
  }
}

// Auto-resize textarea to fit content
function autoResizeTextarea() {
  chatInputBoxRef.value?.autoResize()
}

// Agent control functions
async function stopAgent() {
  try {
    // Suppress stale items from in-flight operations until agent responds to stop
    suppressingPostStop.value = true
    const response = await fetch(`/api/chats/${chatId.value}/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    if (!response.ok) {
      console.error('Failed to stop agent:', await response.text())
      suppressingPostStop.value = false
    }
    // suppressingPostStop is cleared when the agent's response arrives (chat_item_created handler)
  } catch (error) {
    console.error('Error stopping agent:', error)
    suppressingPostStop.value = false
  }
}

async function interruptPendingHITLRequest() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/abort`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })

    if (!response.ok) {
      console.error('Failed to interrupt pending HITL request:', await response.text())
      return false
    }

    agentRunning.value = false
    agentPlanning.value = false
    agentPaused.value = false
    runningNodes.value = []
    return true
  } catch (error) {
    console.error('Error interrupting pending HITL request:', error)
    return false
  }
}

async function cancelAgent() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/abort`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    if (response.ok) {
      agentRunning.value = false
      agentPlanning.value = false
      agentPaused.value = false
      runningNodes.value = []
    } else {
      console.error('Failed to cancel agent:', await response.text())
    }
  } catch (error) {
    console.error('Error cancelling agent:', error)
  }
}

async function rerunPlan() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/rerun`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    if (response.ok) {
      agentRunning.value = true
      agentPaused.value = false
    } else {
      console.error('Failed to rerun plan:', await response.text())
    }
  } catch (error) {
    console.error('Error rerunning plan:', error)
  }
}

function togglePause() {
  if (agentPaused.value) {
    resumeAgent()
  } else {
    pauseAgent()
  }
}

function toggleView() {
  viewMode.value = viewMode.value === 'chat' ? 'raw' : 'chat'
  focusedItemId.value = null // Clear focus when toggling
  // Fetch debug messages and traces when switching to raw view
  if (viewMode.value === 'raw') {
    fetchDebugMessages()
    fetchTraces()
  }
}

function toggleSettingsPanel() {
  settingsPanelVisible.value = !settingsPanelVisible.value
  localStorage.setItem(_chatSettingsKey, String(settingsPanelVisible.value))
}

function formatQuotaReset(isoString) {
  if (!isoString) return ''
  const reset = new Date(isoString)
  const now = new Date()
  const diffMs = reset.getTime() - now.getTime()
  if (diffMs <= 0) return 'now'
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 60) return `${diffMins}m`
  const diffHours = Math.floor(diffMins / 60)
  const remainMins = diffMins % 60
  if (diffHours < 24) return remainMins > 0 ? `${diffHours}h ${remainMins}m` : `${diffHours}h`
  const diffDays = Math.floor(diffHours / 24)
  const remainHours = diffHours % 24
  return remainHours > 0 ? `${diffDays}d ${remainHours}h` : `${diffDays}d`
}

async function openCloudDashboard() {
  const url = cloudBaseUrl.value + '/link/dashboard'
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } else {
    window.open(url, '_blank')
  }
}

const cloudSigningIn = ref(false)

async function handleCloudSignIn() {
  cloudSigningIn.value = true
  try {
    await signInWithBrowser()
    // Refresh models directly rather than relying on the isAuthenticated
    // watcher: the hero can be visible while already authenticated (e.g. a
    // transient cloud-catalog fetch left every model unavailable), in which
    // case auth state doesn't change and the watcher never fires.
    clearLLMNotConfiguredErrors()
    invalidateModelCache()
    await fetchAvailableModels(chat.value?.project_id, true)
  } catch (error) {
    addToast({ type: 'error', message: error.message || 'Sign in failed' })
  } finally {
    cloudSigningIn.value = false
  }
}

// When auth state changes, refresh models and clean up stale CTA errors, then retry
watch(isAuthenticated, async (authed) => {
  if (authed) {
    // Check if the chat ended with an LLM setup error — if so, replay the last user message
    const lastItem = items.value[items.value.length - 1]
    const hasLLMError = lastItem?.item_type === 'error' && isLLMSetupError(lastItem)
    const lastUserMessage = hasLLMError
      ? [...items.value].reverse().find(item => item.item_type === 'user_message' && item.message_text)
      : null

    clearLLMNotConfiguredErrors()
    invalidateModelCache()
    await fetchAvailableModels(chat.value?.project_id, true)

    if (lastUserMessage) {
      await nextTick()
      replayFromHere(lastUserMessage)
    }
  }
})

async function openPricingPage() {
  const url = cloudBaseUrl.value + '/link/pricing'
  if (isTauri()) {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } else {
    window.open(url, '_blank')
  }
}

const accountRefreshing = ref(false)

async function refreshAccountAndRetry() {
  accountRefreshing.value = true
  try {
    const { fetchCloudAccount } = useCloudAccount()
    await fetchCloudAccount()
    addToast({ type: 'info', message: 'Account refreshed. Try sending your message again.' })
  } catch (error) {
    addToast({ type: 'error', message: 'Could not refresh account info.' })
  } finally {
    accountRefreshing.value = false
  }
}

function openAISettings() {
  // Dispatch a custom event that App.vue can listen for to open the settings modal
  window.dispatchEvent(new CustomEvent('open-settings', { detail: 'ai-services' }))
}

function toggleRawPlan(itemId) {
  if (rawPlanItemIds.has(itemId)) {
    rawPlanItemIds.delete(itemId)
  } else {
    rawPlanItemIds.add(itemId)
  }
}

function showDebugForItem(itemId) {
  focusedItemId.value = itemId
  viewMode.value = 'raw'
  fetchDebugMessages()
  fetchTraces()
  // Scroll to the focused item after Vue updates the DOM
  nextTick(() => {
    const element = document.querySelector(`[data-item-id="${itemId}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      // Add a brief highlight effect
      element.classList.add('ring-2', 'ring-purple-500')
      setTimeout(() => {
        element.classList.remove('ring-2', 'ring-purple-500')
      }, 2000)
    }
  })
}

async function fetchDebugMessages() {
  debugLoading.value = true
  debugMessages.value = null
  debugSystemPrompt.value = null
  debugAgentVersion.value = null
  try {
    const response = await fetch(`/api/chats/${chatId.value}/debug-messages`, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      const data = await response.json()
      debugMessages.value = data
      debugSystemPrompt.value = data.system_prompt || null
      debugAgentVersion.value = data.agent_version || null
    }
  } catch (error) {
    console.error('Failed to fetch debug messages:', error)
  } finally {
    debugLoading.value = false
  }
}

function copySystemPrompt() {
  if (debugSystemPrompt.value) {
    copyToClipboard(debugSystemPrompt.value)
    addToast('System prompt copied to clipboard', 'success')
  }
}

async function fetchTraces() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/traces`, {
      headers: { 'X-Profile-ID': getCurrentProfileId() }
    })
    if (response.ok) {
      const data = await response.json()
      chatTraces.value = data.items || []
    }
  } catch (error) {
    console.error('Failed to fetch traces:', error)
  }
}

// Find trace for an item based on type and timestamp proximity
function getTraceForItem(item) {
  if (!chatTraces.value.length) return null

  const itemTime = new Date(item.created_at).getTime()

  // For system items with plan data (has nodes array), look for main_agent trace
  if (item.item_type === 'system' && item.item_metadata) {
    try {
      const metadata = typeof item.item_metadata === 'string'
        ? JSON.parse(item.item_metadata)
        : item.item_metadata
      if (metadata && metadata.nodes && Array.isArray(metadata.nodes)) {
        // Find closest main_agent trace before this item
        const mainAgentTraces = chatTraces.value
          .filter(t => t.trace_type === 'main_agent')
          .filter(t => new Date(t.created_at).getTime() <= itemTime + 5000) // Within 5s after
          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
        return mainAgentTraces[0] || null
      }
    } catch (e) {}
  }

  // For tool_call items with craft_prompts, look for prompt_craft trace
  if (item.item_type === 'tool_call' && item.tool_name === 'craft_prompts') {
    const craftTraces = chatTraces.value
      .filter(t => t.trace_type === 'prompt_craft')
      .filter(t => {
        const traceTime = new Date(t.created_at).getTime()
        return Math.abs(traceTime - itemTime) < 10000 // Within 10s
      })
      .sort((a, b) => Math.abs(new Date(a.created_at).getTime() - itemTime) - Math.abs(new Date(b.created_at).getTime() - itemTime))
    return craftTraces[0] || null
  }

  // For tool_result items from craft_prompts
  if (item.item_type === 'tool_result' && item.tool_name === 'craft_prompts') {
    const craftTraces = chatTraces.value
      .filter(t => t.trace_type === 'prompt_craft')
      .filter(t => {
        const traceTime = new Date(t.created_at).getTime()
        return Math.abs(traceTime - itemTime) < 10000
      })
      .sort((a, b) => Math.abs(new Date(a.created_at).getTime() - itemTime) - Math.abs(new Date(b.created_at).getTime() - itemTime))
    return craftTraces[0] || null
  }

  // For resolve_reference tool calls/results
  if ((item.item_type === 'tool_call' || item.item_type === 'tool_result') && item.tool_name === 'resolve_reference') {
    const refTraces = chatTraces.value
      .filter(t => t.trace_type === 'resolve_reference')
      .filter(t => {
        const traceTime = new Date(t.created_at).getTime()
        return Math.abs(traceTime - itemTime) < 10000
      })
      .sort((a, b) => Math.abs(new Date(a.created_at).getTime() - itemTime) - Math.abs(new Date(b.created_at).getTime() - itemTime))
    return refTraces[0] || null
  }

  // For delegate tool calls, traces are linked by tool_call_id = parent item id
  if (item.item_type === 'tool_call' && item.tool_name === 'delegate') {
    return { type: 'delegate', parentItemId: item.id }
  }

  return null
}

// Check if item has an associated trace
function hasTraceForItem(item) {
  return getTraceForItem(item) !== null
}

function openTraceForItem(item) {
  // For plan items, show traces scoped to this plan's ID
  if (item.item_type === 'system' && item.item_metadata) {
    try {
      const metadata = typeof item.item_metadata === 'string'
        ? JSON.parse(item.item_metadata)
        : item.item_metadata
      if (metadata && metadata.nodes && Array.isArray(metadata.nodes)) {
        // Extract plan ID from metadata (stored as "id" in plan.to_dict())
        const planId = metadata.id
        // Open trace list filtered by plan_id
        selectedTraceId.value = null
        tracePlanId.value = planId || null
        showTraceModal.value = true
        return
      }
    } catch (e) {}
  }

  // For other items (tool calls), go directly to the matching trace
  const trace = getTraceForItem(item)
  if (trace) {
    // Delegate traces: open list filtered by tool_call_id
    if (trace.type === 'delegate') {
      selectedTraceId.value = null
      tracePlanId.value = null
      traceToolCallId.value = String(trace.parentItemId)
      showTraceModal.value = true
      return
    }
    selectedTraceId.value = trace.id
    tracePlanId.value = null
    traceToolCallId.value = null
    showTraceModal.value = true
  }
}

// Context limit for the model (approximate — user can adjust if their model differs)
const contextLimit = 131072

const tokenUsagePercent = computed(() => {
  const ctx = llmUsage.value?.context_tokens
  if (!ctx) return 0
  return Math.min(100, (ctx / contextLimit) * 100)
})

function formatTokenCount(n) {
  if (!n) return '0'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

// Dev mode: compute session token totals from loaded chat items
const sessionTokenTotals = computed(() => {
  const totals = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, reasoning_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, model: '', turns: 0, total_llm_seconds: 0, avg_tps: 0 }
  if (!items.value) return totals
  for (const item of items.value) {
    const usage = item.item_metadata?.llm_usage
    if (usage) {
      totals.prompt_tokens += usage.prompt_tokens || 0
      totals.completion_tokens += usage.completion_tokens || 0
      totals.total_tokens += usage.total_tokens || 0
      totals.reasoning_tokens += usage.reasoning_tokens || 0
      totals.cache_creation_input_tokens += usage.cache_creation_input_tokens || 0
      totals.cache_read_input_tokens += usage.cache_read_input_tokens || 0
      totals.total_llm_seconds += usage.elapsed_seconds || 0
      totals.model = usage.model || totals.model
      totals.turns++
    }
  }
  // Prefer live WebSocket data when available (more up-to-date during agent runs,
  // and covers turns where no text item was persisted with usage metadata)
  if (llmUsage.value) {
    totals.model = llmUsage.value.model || totals.model
    // If no items have persisted usage yet, use live WebSocket data
    if (totals.turns === 0) {
      totals.prompt_tokens = llmUsage.value.prompt_tokens || 0
      totals.completion_tokens = llmUsage.value.completion_tokens || 0
      totals.total_tokens = llmUsage.value.total_tokens || 0
      totals.reasoning_tokens = llmUsage.value.reasoning_tokens || 0
      totals.cache_creation_input_tokens = llmUsage.value.cache_creation_input_tokens || 0
      totals.cache_read_input_tokens = llmUsage.value.cache_read_input_tokens || 0
      totals.total_llm_seconds = llmUsage.value.cumulative_llm_seconds || 0
      if (totals.prompt_tokens || totals.completion_tokens) totals.turns = 1
    }
  }
  // Weighted average: total completion tokens / total LLM wall-clock time
  if (totals.total_llm_seconds > 0) {
    totals.avg_tps = totals.completion_tokens / totals.total_llm_seconds
  }
  return totals
})

function getContextSummary() {
  if (!debugMessages.value?.messages) return ''

  // Count messages by role
  const counts = { system: 0, user: 0, assistant: 0, tool: 0 }
  let toolCalls = 0
  let totalChars = 0

  for (const msg of debugMessages.value.messages) {
    if (msg.role in counts) {
      counts[msg.role]++
    }
    if (msg.tool_calls) {
      toolCalls += msg.tool_calls.length
    }
    if (msg.content) {
      if (typeof msg.content === 'string') {
        totalChars += msg.content.length
      } else if (Array.isArray(msg.content)) {
        // Multimodal content — estimate image blocks as ~85 tokens (low) or ~765 tokens (high)
        // instead of counting the base64 string characters
        for (const block of msg.content) {
          if (block.type === 'text') {
            totalChars += (block.text || '').length
          } else if (block.type === 'image_url') {
            totalChars += 340 // ~85 tokens * 4 chars/token
          }
        }
      } else {
        totalChars += JSON.stringify(msg.content).length
      }
    }
  }

  const estTokens = Math.round(totalChars / 4)
  let summary = `${debugMessages.value.messages.length} msgs (${counts.user}u ${counts.assistant}a ${counts.tool}t ${toolCalls}tc)`
  summary += ` · ~${formatTokenCount(estTokens)} tokens est`
  if (llmUsage.value?.prompt_tokens) {
    summary += ` · ${formatTokenCount(llmUsage.value.prompt_tokens)} actual`
  }
  return summary
}

async function abortPlan() {
  try {
    const response = await fetch(`/api/chats/${chatId.value}/abort`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Profile-ID': getCurrentProfileId()
      }
    })

    if (!response.ok) {
      console.error('Failed to abort plan')
    }
  } catch (error) {
    console.error('Error aborting plan:', error)
  }
}

async function updateParameter(name, value) {
  try {
    // Get current generation settings
    const genSettings = chat.value?.generation_settings || { parameters: {}, locked: [] }
    const params = genSettings.parameters || {}

    // Update the parameter
    params[name] = value
    genSettings.parameters = params

    const response = await fetch(`/api/chats/${chatId.value}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        generation_settings: JSON.stringify(genSettings)
      })
    })

    if (!response.ok) {
      throw new Error('Failed to update parameter')
    }

    // Update local chat object
    const updatedChat = await response.json()
    chat.value = updatedChat
  } catch (error) {
    console.error('Error updating parameter:', error)
  }
}

async function updateSetting(name, value) {
  try {
    // Get current generation settings
    const genSettings = chat.value?.generation_settings || { parameters: {}, locked: [] }

    // Update the setting
    if (name === 'loras') {
      genSettings.loras = value
    } else if (name === 'generator') {
      genSettings.generator = value
    } else if (name === 'model') {
      genSettings.model = value
    } else if (name === 'output_folder') {
      genSettings.output_folder = value
    }

    const response = await fetch(`/api/chats/${chatId.value}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        generation_settings: JSON.stringify(genSettings)
      })
    })

    if (!response.ok) {
      throw new Error('Failed to update setting')
    }

    // Update local chat object
    const updatedChat = await response.json()
    chat.value = updatedChat
  } catch (error) {
    console.error('Error updating setting:', error)
  }
}

async function toggleLock(param) {
  try {
    // Get current generation settings
    const genSettings = chat.value?.generation_settings || { parameters: {}, locked: [] }
    const locked = genSettings.locked || []

    // Toggle lock status
    if (param === 'resolution') {
      // Toggle both width and height
      const hasWidthLock = locked.includes('width')
      const hasHeightLock = locked.includes('height')

      if (hasWidthLock || hasHeightLock) {
        // Unlock both
        genSettings.locked = locked.filter(p => p !== 'width' && p !== 'height')
      } else {
        // Lock both
        genSettings.locked = [...locked, 'width', 'height']
      }
    } else {
      // Toggle single parameter
      if (locked.includes(param)) {
        genSettings.locked = locked.filter(p => p !== param)
      } else {
        genSettings.locked = [...locked, param]
      }
    }

    const response = await fetch(`/api/chats/${chatId.value}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        generation_settings: JSON.stringify(genSettings)
      })
    })

    if (!response.ok) {
      throw new Error('Failed to toggle lock')
    }

    // Update local chat object
    const updatedChat = await response.json()
    chat.value = updatedChat
  } catch (error) {
    console.error('Error toggling lock:', error)
  }
}

// Scroll to bottom of messages
function scrollToBottom() {
  if (messagesContainer.value) {
    // Use smooth scroll for better UX, but fall back to instant for initial load
    messagesContainer.value.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'instant'
    })
  }
}

// Set up WebSocket event subscriptions for real-time updates
// Uses the shared singleton WebSocket composable (profile filtering is handled by the composable)
function setupWebSocketSubscriptions() {
  // Clean up any existing subscriptions first
  cleanupWebSocketSubscriptions()

  // chat_item_created - new items added to chat
  wsUnsubscribes.push(onWsEvent('chat_item_created', (data) => {
    if (data.chat_id !== chatId.value) return
    const newItem = data.item
    const metadata = typeof newItem.item_metadata === 'string'
      ? JSON.parse(newItem.item_metadata || '{}')
      : (newItem.item_metadata || {})

    // Handle stop event: this is the stop marker from the backend
    if (metadata.stop_event) {
      // The stop marker itself is not suppressed — let it through so it renders as "Interrupted"
      suppressingPostStop.value = false
    }

    // Suppress stale items from in-flight operations after stop (but allow the stop marker and agent response)
    if (suppressingPostStop.value && !metadata.stop_event) {
      console.log('Suppressing post-stop item:', newItem.item_type, newItem.id)
      return
    }

    // Debug log for generation items
    if (newItem.item_type === 'generated_media') {
      console.log('Generated media item received:', newItem)
    }

    // Check if item already exists (avoid duplicates)
    const existingIndex = items.value.findIndex(item => item.id === newItem.id)
    if (existingIndex === -1) {
      // Insert in correct position by ID to maintain chronological order
      const insertIdx = items.value.findIndex(item => item.id > newItem.id)
      if (insertIdx === -1) {
        items.value.push(newItem)
      } else {
        items.value.splice(insertIdx, 0, newItem)
      }
      if (newItem.item_type === 'hitl_request' && isActiveHITLRequest(newItem)) {
        agentRunning.value = false
        agentPlanning.value = false
        agentPaused.value = true
        runningNodes.value = []
      }
      if (newItem.item_type === 'hitl_response') {
        agentPaused.value = false
      }
      if (viewMode.value !== 'raw') {
        nextTick(() => {
          scrollToBottom()
        })
      }
    }
  }))

  // chat_item_updated - existing items modified
  wsUnsubscribes.push(onWsEvent('chat_item_updated', (data) => {
    if (data.chat_id !== chatId.value) return
    const updatedItem = data.item
    const index = items.value.findIndex(item => item.id === updatedItem.id)
    if (index !== -1) {
      items.value[index] = updatedItem
    }
  }))

  // chat_item_deleted - items removed (e.g., empty thinking-only messages)
  wsUnsubscribes.push(onWsEvent('chat_item_deleted', (data) => {
    if (data.chat_id !== chatId.value) return
    const deletedId = data.item_id
    items.value = items.value.filter(item => item.id !== deletedId)
  }))

  // chat_updated - chat details changed (e.g., auto-naming, settings)
  wsUnsubscribes.push(onWsEvent('chat_updated', (data) => {
    if (data.chat_id !== chatId.value) return
    chat.value = data.chat
    // If settings changed, we could refresh tool parameters here if needed
    if (data.settings_changed) {
      console.log('Chat settings updated via WebSocket')
    }
  }))

  // agent_started - agent began processing
  wsUnsubscribes.push(onWsEvent('agent_started', (data) => {
    if (data.chat_id !== chatId.value) return
    agentRunning.value = true
    agentPlanning.value = false
    agentPaused.value = false
    nodeStates.value = {} // Clear node states for fresh execution tracking
  }))

  // agent_planning - agent is creating a plan
  wsUnsubscribes.push(onWsEvent('agent_planning', (data) => {
    if (data.chat_id !== chatId.value) return
    agentPlanning.value = true
  }))

  // agent_executing - plan created, now executing
  wsUnsubscribes.push(onWsEvent('agent_executing', (data) => {
    if (data.chat_id !== chatId.value) return
    agentPlanning.value = false
  }))

  // agent_node_progress - node execution progress updates
  wsUnsubscribes.push(onWsEvent('agent_node_progress', (data) => {
    if (data.chat_id !== chatId.value) return
    const { node_id, event, node_type, tool_name, display_name, display_name_active } = data
    if (event === 'started') {
      runningNodes.value = [...runningNodes.value.filter(n => n.node_id !== node_id), { node_id, node_type, tool_name, display_name, display_name_active }]
      nodeStates.value = {
        ...nodeStates.value,
        [node_id]: { status: 'running', display_name, display_name_active }
      }
    } else if (event === 'completed') {
      runningNodes.value = runningNodes.value.filter(n => n.node_id !== node_id)
      // Include output metadata for tools that return analysis results
      const output = data.result_metadata ? { metadata: data.result_metadata } : null
      nodeStates.value = {
        ...nodeStates.value,
        [node_id]: { status: 'completed', display_name, output }
      }
    } else if (event === 'failed') {
      runningNodes.value = runningNodes.value.filter(n => n.node_id !== node_id)
      nodeStates.value = {
        ...nodeStates.value,
        [node_id]: { status: 'failed', display_name }
      }
    } else if (event === 'progress') {
      // Update running node with progress info (e.g., "3/9")
      runningNodes.value = runningNodes.value.map(n =>
        n.node_id === node_id ? { ...n, current: data.current, total: data.total } : n
      )
    }
  }))

  // agent_stopped - agent finished (covers all stop reasons: completed, error, cancelled, paused)
  wsUnsubscribes.push(onWsEvent('agent_stopped', (data) => {
    if (data.chat_id !== chatId.value) return
    const { reason, error } = data
    console.log(`Agent stopped: reason=${reason}`, error ? `error=${error}` : '')

    agentRunning.value = false
    agentPlanning.value = false
    runningNodes.value = []

    // Handle paused state separately (agent can be resumed)
    if (reason === 'paused') {
      agentPaused.value = true
    } else {
      agentPaused.value = false
    }
  }))

  // agent_paused - agent was paused (legacy, now handled by agent_stopped with reason=paused)
  wsUnsubscribes.push(onWsEvent('agent_paused', (data) => {
    if (data.chat_id !== chatId.value) return
    console.log('Agent paused confirmed')
    agentRunning.value = false
    agentPaused.value = true
  }))

  // plan_status_changed - plan status updated
  wsUnsubscribes.push(onWsEvent('plan_status_changed', (data) => {
    if (data.chat_id !== chatId.value) return
    const { status, manually_paused } = data
    console.log('Plan status changed:', status, 'manually_paused:', manually_paused)

    // Find the most recent plan item and update its status
    for (let i = items.value.length - 1; i >= 0; i--) {
      const item = items.value[i]
      if (item.item_type === 'system' && hasPlanData(item)) {
        try {
          const planData = typeof item.item_metadata === 'string'
            ? JSON.parse(item.item_metadata)
            : item.item_metadata
          planData.status = status
          if (planData.variables) {
            planData.variables._manually_paused = manually_paused
          } else {
            planData.variables = { _manually_paused: manually_paused }
          }
          items.value[i] = {
            ...item,
            item_metadata: JSON.stringify(planData)
          }
        } catch (e) {
          console.error('Error updating plan status:', e)
        }
        break
      }
    }
  }))

  // plan_node_updated - a specific plan node was updated (e.g., tool changed)
  wsUnsubscribes.push(onWsEvent('plan_node_updated', (data) => {
    if (data.chat_id !== chatId.value) return
    const { node_id, node } = data
    console.log('Plan node updated:', node_id, node)

    // Find the most recent plan item and update the node
    for (let i = items.value.length - 1; i >= 0; i--) {
      const item = items.value[i]
      if (item.item_type === 'system' && hasPlanData(item)) {
        try {
          const planData = typeof item.item_metadata === 'string'
            ? JSON.parse(item.item_metadata)
            : item.item_metadata
          // Find and update the node
          if (planData.nodes) {
            const nodeIndex = planData.nodes.findIndex((n: any) => n.id === node_id)
            if (nodeIndex >= 0) {
              planData.nodes[nodeIndex] = node
              items.value[i] = {
                ...item,
                item_metadata: JSON.stringify(planData)
              }
              console.log('Updated node in plan:', node_id)
            }
          }
        } catch (e) {
          console.error('Error updating plan node:', e)
        }
        break
      }
    }
  }))

  // media_permanently_deleted - media was permanently deleted (from any client)
  wsUnsubscribes.push(onWsEvent('media_permanently_deleted', (data) => {
    const mediaIds = data.media_ids || (data.media_id ? [data.media_id] : [])
    for (const mediaId of mediaIds) {
      handleMediaPermanentDelete(mediaId)
    }
  }))

  // media_deleted - media was trashed (soft-deleted)
  wsUnsubscribes.push(onWsEvent('media_deleted', (data) => {
    const mediaId = data.media_id
    if (!mediaId) return
    handleMediaTrashed(mediaId)
  }))

  // media_bulk_deleted - multiple media items were trashed
  wsUnsubscribes.push(onWsEvent('media_bulk_deleted', (data) => {
    const mediaIds = data.media_ids || []
    for (const mediaId of mediaIds) {
      handleMediaTrashed(mediaId)
    }
  }))

  // llm_usage - token usage stats from LLM calls
  wsUnsubscribes.push(onWsEvent('llm_usage', (data) => {
    llmUsage.value = data
  }))
}

// Clean up WebSocket subscriptions
function cleanupWebSocketSubscriptions() {
  wsUnsubscribes.forEach(unsub => unsub())
  wsUnsubscribes.length = 0
}

// Attach any media handed off for this chat (drag-drop / "Send to Chat").
// One-shot consumption from the store — see usePendingMedia for why this isn't
// a URL query param.
function checkPendingMedia() {
  const ids = consumePendingMedia('chat', chatId.value)
  if (!ids) return
  for (const id of ids) {
    addAttachmentFromMediaId(id)
  }
}

// Check for initial message from Home screen
function checkInitialMessage() {
  const text = route.query.initialMessage
  if (!text) return
  const attachmentIds = route.query.attachmentIds
  router.replace({ query: {} })
  messageInput.value = text
  if (attachmentIds) {
    const ids = attachmentIds.split(',').map(id => parseInt(id)).filter(id => !isNaN(id))
    for (const id of ids) {
      addAttachmentFromMediaId(id)
    }
  }
  nextTick(() => sendMessage())
}

// Initialize
// Open external links in system browser instead of the Tauri webview
function handleLinkClick(e) {
  const anchor = e.target.closest('a[href]')
  if (!anchor) return
  const href = anchor.getAttribute('href')
  if (!href || href.startsWith('#') || href.startsWith('/')) return
  e.preventDefault()
  if (isTauri()) {
    import('@tauri-apps/plugin-shell').then(({ open }) => open(href))
  } else {
    window.open(href, '_blank')
  }
}

function resolveChatIdSource(): number | null {
  // Prefer the prop when embedded as a component, otherwise use the route.
  const raw = props.chatId != null ? props.chatId : route.params.id
  if (raw == null || raw === '') return null
  const n = typeof raw === 'number' ? raw : parseInt(String(raw))
  return Number.isFinite(n) ? n : null
}

onMounted(() => {
  chatId.value = resolveChatIdSource()
  loadChat()
  loadMarkers()
  loadEligibleSkills()
  window.addEventListener('stimpacks-changed', handleSkillsChanged)
  // Set up WebSocket subscriptions (shared singleton handles connection)
  setupWebSocketSubscriptions()
  loadItems().then(() => {
    // Sync agent status from backend (recovers from stale state after server restart)
    syncAgentStatus()
    // Check for pending media after initial load
    checkPendingMedia()
    checkInitialMessage()
  })
  // Intercept link clicks in chat messages to open in system browser
  if (messagesContainer.value) {
    messagesContainer.value.addEventListener('click', handleLinkClick)
  }
})

// Handle KeepAlive re-activation (component waking up from cache)
onActivated(async () => {
  // Re-subscribe to WebSocket events when component becomes active again
  setupWebSocketSubscriptions()
  // Wait for route to be fully updated before checking for pending media
  // onActivated can fire before Vue Router finishes updating the route object
  await nextTick()
  checkPendingMedia()
  checkInitialMessage()
})

// Handle KeepAlive deactivation (component going into cache)
onDeactivated(() => {
  console.log('[onDeactivated] cleaning up WebSocket subscriptions')
  cleanupWebSocketSubscriptions()
})

onUnmounted(() => {
  cleanupWebSocketSubscriptions()
  if (queueWatchdogTimer) {
    clearInterval(queueWatchdogTimer)
    queueWatchdogTimer = null
  }
  window.removeEventListener('profile-changed', handleProfileChanged)
  window.removeEventListener('markers-changed', loadMarkers)
  window.removeEventListener('stimpacks-changed', handleSkillsChanged)
  if (messagesContainer.value) {
    messagesContainer.value.removeEventListener('click', handleLinkClick)
  }
  if (loadMoreObserver.value) {
    loadMoreObserver.value.disconnect()
  }
})

// Handle profile changes - redirect to chat list since current chat may not exist in new profile
function handleProfileChanged() {
  console.log('Profile changed in ChatView, redirecting to chat list')
  router.push('/chats')
}

// Listen for profile changes
window.addEventListener('profile-changed', handleProfileChanged)

// Listen for markers config changes
window.addEventListener('markers-changed', loadMarkers)

// Watch for route changes (only relevant when this view owns the route, not
// when it's embedded as a component driven by the chatId prop)
watch(() => route.params.id, (newId) => {
  if (props.chatId != null) return
  if (newId) {
    const parsed = parseInt(newId)
    // Re-navigating to the chat we're already on (e.g. dropping a second image
    // onto the active chat in the sidebar) must NOT clear attachments: the
    // global pendingMedia watch may have already attached the new media before
    // this watch runs, and an unconditional clear would wipe it.
    const chatChanged = chatId.value !== parsed
    // Update chatId - subscriptions filter by this value automatically
    chatId.value = parsed
    loading.value = true
    items.value = []
    // Drop attachments from the previous chat synchronously, before any pending
    // media for the new chat gets attached, so the clear can't wipe it.
    if (chatChanged) inputAttachments.value = []
    // Reset agent state for new chat. The queue must not carry over — a
    // message queued in the previous chat would otherwise post to this one.
    if (chatChanged) messageQueue.value = []
    agentRunning.value = false
    agentPaused.value = false
    agentPlanning.value = false
    runningNodes.value = []
    nodeStates.value = {}
    loadChat()
    loadItems().then(() => {
      // Sync agent status for the new chat
      syncAgentStatus()
      checkPendingMedia()
    })
  }
})

// React to media handed off for the currently-viewed chat ("Send to Chat" to the
// same chat, where the route doesn't change).
watch(pendingMedia, () => {
  checkPendingMedia()
}, { flush: 'post' })

// When embedded, the chatId comes in via prop instead of the route — react
// to prop changes (e.g. the parent flow resolves its scoped chat lazily).
watch(() => props.chatId, (newId) => {
  if (newId == null) return
  const n = resolveChatIdSource()
  if (n == null || n === chatId.value) return
  chatId.value = n
  loading.value = true
  items.value = []
  messageQueue.value = []
  agentRunning.value = false
  agentPaused.value = false
  agentPlanning.value = false
  runningNodes.value = []
  nodeStates.value = {}
  loadChat()
  loadItems().then(() => {
    syncAgentStatus()
    inputAttachments.value = []
  })
})

// Sync agent status on WebSocket reconnect
// This recovers from stale state if server restarted during agent execution
watch(wsConnected, (connected, wasConnected) => {
  if (connected && !wasConnected && chatId.value) {
    console.log('[WebSocket] Reconnected, syncing agent status')
    syncAgentStatus()
  }
})
</script>

<style scoped>
.chat-item {
  animation: fadeIn 0.2s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* JSON syntax highlighting - dark theme */
[data-theme="dark"] .json-highlighted :deep(.json-key) {
  color: #93c5fd; /* blue-300 */
}
[data-theme="dark"] .json-highlighted :deep(.json-string) {
  color: #86efac; /* green-300 */
}
[data-theme="dark"] .json-highlighted :deep(.json-number) {
  color: #fdba74; /* orange-300 */
}
[data-theme="dark"] .json-highlighted :deep(.json-boolean) {
  color: #c4b5fd; /* violet-300 */
}

/* JSON syntax highlighting - light theme */
[data-theme="light"] .json-highlighted :deep(.json-key) {
  color: #2563eb; /* blue-600 */
}
[data-theme="light"] .json-highlighted :deep(.json-string) {
  color: #16a34a; /* green-600 */
}
[data-theme="light"] .json-highlighted :deep(.json-number) {
  color: #ea580c; /* orange-600 */
}
[data-theme="light"] .json-highlighted :deep(.json-boolean) {
  color: #7c3aed; /* violet-600 */
}

/* Debug view action buttons - dark theme */
[data-theme="dark"] .debug-btn-purple { background: rgb(88 28 135 / 0.5); color: #c4b5fd; }
[data-theme="dark"] .debug-btn-purple:hover { background: #7e22ce; color: #fff; }
[data-theme="dark"] .debug-btn-emerald { background: rgb(6 78 59 / 0.5); color: #6ee7b7; }
[data-theme="dark"] .debug-btn-emerald:hover { background: #047857; color: #fff; }
[data-theme="dark"] .debug-btn-amber { background: rgb(120 53 15 / 0.5); color: #fcd34d; }
[data-theme="dark"] .debug-btn-amber:hover { background: #b45309; color: #fff; }
[data-theme="dark"] .debug-btn-red { background: rgb(127 29 29 / 0.5); color: #fca5a5; }
[data-theme="dark"] .debug-btn-red:hover { background: #b91c1c; color: #fff; }

/* Debug view action buttons - light theme */
[data-theme="light"] .debug-btn-purple { background: #ede9fe; color: #6d28d9; }
[data-theme="light"] .debug-btn-purple:hover { background: #ddd6fe; color: #5b21b6; }
[data-theme="light"] .debug-btn-emerald { background: #d1fae5; color: #047857; }
[data-theme="light"] .debug-btn-emerald:hover { background: #a7f3d0; color: #065f46; }
[data-theme="light"] .debug-btn-amber { background: #fef3c7; color: #b45309; }
[data-theme="light"] .debug-btn-amber:hover { background: #fde68a; color: #92400e; }
[data-theme="light"] .debug-btn-red { background: #fee2e2; color: #b91c1c; }
[data-theme="light"] .debug-btn-red:hover { background: #fecaca; color: #991b1b; }

/* Animated thinking dots */
.thinking-dots::after {
  content: '';
  animation: thinkingDots 1.5s infinite;
}

@keyframes thinkingDots {
  0%, 20% { content: '.'; }
  40% { content: '..'; }
  60%, 100% { content: '...'; }
}

/* Typing indicator dots */
.typing-dot {
  width: 8px;
  height: 8px;
  background-color: var(--color-text-muted);
  border-radius: 50%;
  animation: typingBounce 1.4s infinite ease-in-out both;
}

.typing-dot:nth-child(1) {
  animation-delay: 0s;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.16s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.32s;
}

@keyframes typingBounce {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.4;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* Fade transition for drop overlay */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ─── Activity Group ─── */
.activity-group {
  max-width: 100%;
  min-width: 0;
}

.activity-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 8px;
  border-radius: 9999px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  line-height: 1.3;
  color: var(--color-text-secondary, #9ca3af);
  background: var(--color-surface, rgba(255,255,255,0.04));
  border: 1px solid var(--color-edge-subtle, rgba(255,255,255,0.06));
  transition: all 0.15s ease;
}
.activity-summary:hover {
  background: var(--color-surface-raised, rgba(255,255,255,0.08));
  border-color: var(--color-edge, rgba(255,255,255,0.1));
  color: var(--color-text-primary, #e5e7eb);
}

.activity-group--running .activity-summary {
  border-color: rgba(96, 165, 250, 0.2);
  background: rgba(96, 165, 250, 0.04);
}

.activity-chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: transform 0.2s ease;
  opacity: 0.5;
}

.activity-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #60a5fa;
  flex-shrink: 0;
  animation: activityPulse 1.5s ease-in-out infinite;
}
@keyframes activityPulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.activity-tool-list {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex-wrap: wrap;
}

.activity-tool-name {
  font-weight: 500;
  white-space: nowrap;
}

.activity-thinking {
  opacity: 0.5;
  font-size: 12px;
  white-space: nowrap;
}
.activity-thinking::before {
  content: '·';
  margin-right: 6px;
  opacity: 0.5;
}
.activity-thinking--solo::before {
  display: none;
}

.activity-failed-badge {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #f87171;
  padding: 1px 6px;
  border-radius: 9999px;
  background: rgba(248, 113, 113, 0.1);
}

.activity-running-badge {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #60a5fa;
}

/* Timeline — tree-line connector style */
.activity-timeline {
  margin-top: 4px;
  margin-left: 18px;
}

.activity-step {
  position: relative;
  display: flex;
  align-items: flex-start;
  min-height: 28px;
}

/* Connector: vertical line + horizontal branch */
.activity-step-connector {
  position: relative;
  width: 16px;
  flex-shrink: 0;
  align-self: stretch;
}

/* Vertical line running down from previous step */
.activity-step-connector::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-edge-subtle, rgba(255,255,255,0.1));
}

/* Last step: vertical line only goes to the branch, not past it */
.activity-step--last .activity-step-connector::before {
  bottom: auto;
  height: 14px;
}

/* Horizontal branch arm */
.activity-step-branch {
  position: absolute;
  left: 0;
  top: 13px;
  width: 12px;
  height: 1px;
  background: var(--color-edge-subtle, rgba(255,255,255,0.1));
}

.activity-details {
  cursor: default;
}

/* Nested delegate timeline — connector lines.
   Per-step ::before vertical lines can gap inside <details>.
   Fix: continuous border-left on the timeline, suppress per-step verticals. */
.activity-details > .activity-timeline {
  border-left: 1px solid var(--color-edge-subtle, rgba(255,255,255,0.1));
  margin-left: 0;
  margin-top: 2px;
}
.activity-details > .activity-timeline .activity-step-connector::before {
  display: none;
}
.activity-details > .activity-timeline .activity-step-connector {
  width: 12px;
}
.activity-details > .activity-timeline .activity-step-branch {
  left: 0;
  width: 10px;
}

.activity-details summary {
  cursor: pointer;
  list-style: none;
}
.activity-details summary::-webkit-details-marker {
  display: none;
}
.activity-details[open] > summary .activity-chevron {
  transform: rotate(90deg);
}

.activity-step-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 3px 8px;
  border-radius: 6px;
  transition: background 0.1s ease;
}
.activity-step-summary:hover {
  background: var(--color-surface, rgba(255,255,255,0.04));
}

.activity-step-name {
  font-weight: 500;
  color: var(--color-text-primary, #e5e7eb);
}

.activity-step-preview {
  color: var(--color-text-muted, #6b7280);
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 350px;
}

.activity-step-content {
  margin: 4px 0 8px 4px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--color-surface, rgba(255,255,255,0.03));
  border: 1px solid var(--color-edge-subtle, rgba(255,255,255,0.04));
  max-height: 300px;
  overflow-y: auto;
}

.activity-code-block {
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(0,0,0,0.2);
  padding: 10px 12px;
  overflow-x: auto;
}

/* Light theme overrides */
[data-theme="light"] .activity-summary {
  color: #6b7280;
  background: #f9fafb;
  border-color: #e5e7eb;
}
[data-theme="light"] .activity-summary:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
  color: #374151;
}
[data-theme="light"] .activity-group--running .activity-summary {
  border-color: rgba(59, 130, 246, 0.2);
  background: rgba(59, 130, 246, 0.03);
}
[data-theme="light"] .activity-step-connector::before,
[data-theme="light"] .activity-step-branch {
  background: #d1d5db;
}
[data-theme="light"] .activity-details > .activity-timeline {
  border-left-color: #d1d5db;
}
[data-theme="light"] .activity-step-name {
  color: #374151;
}
[data-theme="light"] .activity-step-preview {
  color: #9ca3af;
}
[data-theme="light"] .activity-step-summary:hover {
  background: #f3f4f6;
}
[data-theme="light"] .activity-step-content {
  background: #f9fafb;
  border-color: #e5e7eb;
}
[data-theme="light"] .activity-code-block {
  background: #f3f4f6;
  border-color: #e5e7eb;
}
</style>
