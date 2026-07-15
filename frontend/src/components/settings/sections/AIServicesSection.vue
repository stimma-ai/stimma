<template>
  <div class="space-y-6">
    <div>
      <h3 class="text-base font-medium text-content">AI Services</h3>
      <p class="mt-1 text-xs text-content-tertiary">Choose models from your Stimma account, API providers, or your own endpoints.</p>
    </div>

    <section class="rounded-lg border border-edge p-4">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <h4 class="text-sm font-medium text-content">Quick tasks</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">Prompt cleanup, chat names, and other background work.</p>
        </div>
        <div class="shrink-0">
          <SettingsDropdown
            control
            fill
            class="w-72"
            :menu-width="320"
            :model-value="quickTaskModel"
            :options="quickTaskOptions"
            @update:model-value="saveQuickTaskModel"
          />
          <p v-if="selectedQuickModel?.available === false" class="mt-1 text-xs text-red-400">Unavailable. Choose another model.</p>
        </div>
      </div>
    </section>

    <section v-if="voiceSupported" class="rounded-lg border border-edge p-4">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <h4 class="text-sm font-medium text-content">Voice input</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">Processed on this device.</p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <svg v-if="voiceModelReady" class="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
          </svg>
          <SettingsDropdown
            v-model="voiceModel"
            control
            compact
            :menu-width="224"
            :options="voiceModelOptions"
          />
        </div>
      </div>
      <p v-if="!voiceModelReady && privacyLockdownActive" class="mt-3 text-xs text-content-secondary">Downloads are off during Privacy Lockdown.</p>
      <p v-else-if="!voiceModelReady" class="mt-3 text-xs text-content-tertiary">Downloads on first use.</p>
    </section>

    <section>
      <div class="mb-3 flex items-center justify-between gap-3">
        <div>
          <h4 class="text-sm font-medium text-content">Model providers</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">Each provider controls its connection and models.</p>
        </div>
        <div class="flex items-center gap-3">
          <button type="button" @click="refreshAll" class="text-xs text-content-secondary hover:text-content">Refresh</button>
          <button type="button" @click="openAddProvider" class="rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400">Add provider</button>
        </div>
      </div>

      <div class="overflow-hidden rounded-lg border border-edge">
        <button type="button" @click="openStimmaAccount" class="flex w-full items-center gap-4 border-b border-edge px-4 py-3 text-left hover:bg-white/[0.03]">
          <div class="min-w-0 flex-1">
            <div class="stimma-cloud-text text-sm font-medium">Stimma Account</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ modelSummary(cloudModels) }}</div>
            <div v-if="cloudStatus !== 'available' && cloudMessage" class="mt-1 truncate text-xs text-red-400">{{ cloudMessage }}</div>
          </div>
          <div class="shrink-0 text-right">
            <div class="text-xs" :class="cloudStatus === 'available' ? 'text-green-500' : 'text-content-muted'">{{ cloudStatus === 'available' ? 'Ready' : 'Unavailable' }}</div>
            <div class="mt-0.5 text-[11px] text-content-muted">{{ cloudModels.length }} model{{ cloudModels.length === 1 ? '' : 's' }}</div>
          </div>
          <ChevronIcon />
        </button>

        <button
          v-for="provider in providers"
          :key="provider.id"
          type="button"
          @click="openProvider(provider)"
          class="flex w-full items-center gap-4 border-b border-edge px-4 py-3 text-left last:border-b-0 hover:bg-white/[0.03]"
        >
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-content">{{ provider.name }}</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ modelSummary(provider.models) }}</div>
            <div v-if="provider.last_error" class="mt-1 truncate text-xs text-red-400">{{ provider.last_error }}</div>
          </div>
          <div class="shrink-0 text-right">
            <div class="text-xs" :class="provider.last_test_passed === false ? 'text-red-400' : provider.last_test_passed ? 'text-green-500' : 'text-content-muted'">
              {{ provider.last_test_passed === false ? 'Check failed' : provider.last_test_passed ? 'Ready' : 'Not checked' }}
            </div>
            <div class="mt-0.5 text-[11px] text-content-muted">{{ provider.models.length }} model{{ provider.models.length === 1 ? '' : 's' }}</div>
          </div>
          <ChevronIcon />
        </button>

        <button
          v-if="legacyProvider"
          type="button"
          @click="openLegacyProvider"
          class="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-white/[0.03]"
        >
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-content">{{ legacyProvider.name }}</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ legacyProvider.model }}</div>
          </div>
          <div class="shrink-0 text-right">
            <div class="text-xs" :class="legacyProvider.last_test_passed === false ? 'text-red-400' : legacyProvider.last_test_passed ? 'text-green-500' : 'text-content-muted'">
              {{ legacyProvider.last_test_passed === false ? 'Check failed' : legacyProvider.last_test_passed ? 'Ready' : 'Not checked' }}
            </div>
            <div class="mt-0.5 text-[11px] text-content-muted">1 model</div>
          </div>
          <ChevronIcon />
        </button>
      </div>
    </section>

    <!-- Add provider -->
    <Teleport to="body">
      <div v-if="addOpen" class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop p-4 backdrop-blur-sm" @click.self="closeAddProvider" @keydown.escape.stop="closeAddProvider">
        <div class="flex max-h-[88vh] w-[560px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-xl border border-edge bg-surface shadow-2xl">
          <div class="flex items-center justify-between border-b border-edge px-5 py-4">
            <div>
              <h4 class="text-base font-medium text-content">{{ addDraft.kind ? `Add ${kindLabel(addDraft.kind)}` : 'Add a model provider' }}</h4>
              <p v-if="addDraft.kind" class="mt-0.5 text-xs text-content-tertiary">{{ kindDescription(addDraft.kind) }}</p>
            </div>
            <button type="button" @click="closeAddProvider" class="text-sm text-content-muted hover:text-content">Cancel</button>
          </div>

          <div class="overflow-y-auto p-5">
            <div v-if="!addDraft.kind" class="grid grid-cols-2 gap-2">
              <button v-for="kind in providerKinds" :key="kind.id" type="button" @click="selectProviderKind(kind.id)" class="rounded-lg border border-edge bg-white/[0.03] p-4 text-left hover:border-blue-500/50 hover:bg-blue-500/5">
                <div class="text-sm font-medium text-content">{{ kind.name }}</div>
                <div class="mt-1 text-xs leading-relaxed text-content-tertiary">{{ kind.description }}</div>
              </button>
            </div>

            <div v-else-if="addStep === 'connection'" class="space-y-4">
              <label v-if="addDraft.kind === 'local'" class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Name <span class="text-content-muted">(optional)</span></span>
                <input v-model="addDraft.name" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" placeholder="Studio Mac" />
              </label>
              <label v-if="addDraft.kind === 'local'" class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                <input v-model="addDraft.base_url" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" placeholder="http://localhost:1234/v1" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">API key<span v-if="addDraft.kind === 'local'" class="text-content-muted"> (optional)</span></span>
                <input v-model="addDraft.api_key" type="password" autocomplete="off" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" :placeholder="addDraft.kind === 'local' ? 'Leave empty if not required' : 'Paste API key'" />
              </label>
            </div>

            <div v-else class="space-y-3">
              <p class="text-xs text-content-tertiary">Choose the models to show in Stimma.</p>
              <label v-for="model in addDiscoveredModels" :key="model.id" class="flex cursor-pointer items-center gap-3 rounded-lg border border-edge px-3 py-2.5 hover:bg-white/[0.03]">
                <input type="checkbox" :checked="addSelectedModels.has(model.id)" @change="toggleAddModel(model.id)" class="rounded border-edge bg-surface" />
                <span class="min-w-0 flex-1 truncate text-sm text-content">{{ model.name }}</span>
              </label>
            </div>

            <p v-if="addError" class="mt-4 text-xs text-red-400">{{ addError }}</p>
          </div>

          <div v-if="addDraft.kind" class="flex items-center justify-between border-t border-edge px-5 py-4">
            <button type="button" @click="backAddProvider" class="text-xs text-content-secondary hover:text-content">Back</button>
            <button type="button" @click="advanceAddProvider" :disabled="addSaving || (addStep === 'models' && addSelectedModels.size === 0)" class="rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-400 disabled:opacity-50">
              {{ addSaving ? 'Checking…' : addStep === 'models' || !['openrouter', 'local'].includes(addDraft.kind) ? 'Add provider' : 'Continue' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Stimma Account / provider settings -->
    <Teleport to="body">
      <div v-if="managerOpen" class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop p-4 backdrop-blur-sm" @click.self="closeManager" @keydown.escape.stop="closeManager">
        <div class="flex max-h-[90vh] w-[760px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-xl border border-edge bg-surface shadow-2xl">
          <div class="flex items-start justify-between border-b border-edge px-5 py-4">
            <div class="min-w-0">
              <h4 class="truncate text-base font-medium" :class="activeManager === 'stimma' ? 'stimma-cloud-text' : 'text-content'">{{ managerTitle }}</h4>
              <p class="mt-0.5 text-xs text-content-tertiary">{{ managerSubtitle }}</p>
            </div>
            <button type="button" @click="closeManager" class="text-sm text-content-muted hover:text-content">Done</button>
          </div>

          <div class="overflow-y-auto p-5">
            <template v-if="activeManager !== 'stimma' && activeProvider">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-xs text-content-tertiary">Name</span>
                  <input v-model="activeProvider.name" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" />
                </label>
                <label class="block">
                  <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                  <input v-model="activeProvider.base_url" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" />
                </label>
                <label v-if="activeProvider.kind !== 'local'" class="block sm:col-span-2">
                  <span class="mb-1 block text-xs text-content-tertiary">Replace API key</span>
                  <input v-model="providerKeyDraft" type="password" autocomplete="off" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" placeholder="Leave blank to keep the current key" />
                </label>
              </div>
              <div class="mt-3 flex items-center gap-3">
                <button type="button" @click="saveProviderConnection" :disabled="managerSaving" class="rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400 disabled:opacity-50">{{ managerSaving ? 'Checking…' : 'Save connection' }}</button>
                <button type="button" @click="testProvider(activeProvider)" :disabled="testingId === activeProvider.id" class="text-xs text-content-secondary hover:text-content disabled:opacity-50">{{ testingId === activeProvider.id ? 'Testing…' : 'Test all models' }}</button>
                <span v-if="activeProvider.last_tested_at" class="text-[11px] text-content-muted">Tested {{ timeAgo(activeProvider.last_tested_at) }}</span>
              </div>
              <p v-if="managerError" class="mt-2 text-xs text-red-400">{{ managerError }}</p>

              <div v-if="isFlexibleProvider(activeProvider)" class="mt-5 border-t border-edge pt-4">
                <div class="flex items-center justify-between">
                  <div>
                    <h5 class="text-sm font-medium text-content">Shown models</h5>
                    <p class="mt-0.5 text-xs text-content-tertiary">Choose which models appear in Stimma.</p>
                  </div>
                  <button type="button" @click="loadProviderModels(activeProvider)" class="text-xs text-blue-400 hover:text-blue-300">Refresh list</button>
                </div>
                <div v-if="discoveredModels.length" class="mt-3 max-h-48 space-y-2 overflow-y-auto pr-1">
                  <label v-for="model in discoveredModels" :key="model.id" class="flex cursor-pointer items-center gap-3 rounded border border-edge px-3 py-2">
                    <input type="checkbox" :checked="selectedManagerIds.has(model.id)" @change="toggleManagerModel(model.id)" class="rounded border-edge bg-surface" />
                    <span class="min-w-0 flex-1 truncate text-sm text-content">{{ model.name }}</span>
                  </label>
                </div>
                <button v-if="discoveredModels.length" type="button" @click="saveProviderModels" class="mt-3 rounded-md border border-blue-500/50 bg-blue-500/15 px-3 py-1.5 text-xs text-blue-400 hover:bg-blue-500/20">Save shown models</button>
              </div>
            </template>

            <div :class="activeManager === 'stimma' ? '' : 'mt-5 border-t border-edge pt-4'">
              <h5 class="text-sm font-medium text-content">Models</h5>
              <p class="mt-0.5 text-xs text-content-tertiary">Model-specific prompt and compatibility settings.</p>
              <div class="mt-3 space-y-2">
                <div v-for="model in managerModels" :key="model.slug || model.id" class="overflow-hidden rounded-lg border border-edge">
                  <button type="button" @click="toggleModelSettings(model)" class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-white/[0.03]">
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-sm text-content">{{ model.name }}</div>
                      <div class="mt-0.5 text-[11px] text-content-muted">{{ modelVendor(model) }}<span v-if="model.cost_tier"> · {{ model.cost_tier }}</span></div>
                    </div>
                    <span v-if="model.last_test_passed === false" class="text-[11px] text-red-400">Failed</span>
                    <span v-else-if="model.last_test_passed" class="text-[11px] text-green-500">Ready</span>
                    <ChevronIcon :open="customizingModelId === modelKey(model)" />
                  </button>

                  <div v-if="customizingModelId === modelKey(model)" class="space-y-4 border-t border-edge bg-white/[0.015] p-4">
                    <div v-if="model.last_test_results && Object.keys(model.last_test_results).length" class="flex flex-wrap gap-1.5">
                      <span v-for="(result, name) in model.last_test_results" :key="name" class="rounded-md border px-1.5 py-0.5 text-[11px]" :class="result.passed ? 'border-green-500/30 text-green-500' : 'border-red-500/30 text-red-400'">
                        {{ result.passed ? '✓' : '×' }} {{ name }}<span v-if="result.elapsed_ms" class="text-content-muted"> · {{ fmtMs(result.elapsed_ms) }}</span>
                      </span>
                    </div>

                    <div class="rounded-lg border border-edge p-3">
                      <div class="text-xs font-medium text-content">Prompt policy</div>
                      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                        <input type="radio" :name="`policy-${modelKey(model)}`" :checked="modelPrompt(model).content_policy_enabled" @change="modelPrompt(model).content_policy_enabled = true" class="mt-0.5" />
                        <span>
                          <span class="block text-xs text-content">Stimma content policy</span>
                          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Stating the policy typically increases permissiveness and creative control with aligned models, while making refusals clearer.</span>
                        </span>
                      </label>
                      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                        <input type="radio" :name="`policy-${modelKey(model)}`" :checked="!modelPrompt(model).content_policy_enabled" @change="modelPrompt(model).content_policy_enabled = false" class="mt-0.5" />
                        <span>
                          <span class="block text-xs text-content">Model default</span>
                          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Do not add Stimma's policy prompt. The provider or model's built-in policy remains in effect.</span>
                        </span>
                      </label>
                      <label class="mt-3 block">
                        <span class="mb-1 block text-[11px] text-content-tertiary">Additional instructions</span>
                        <textarea v-model="modelPrompt(model).extra_system_prompt" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="Appended to the system prompt for this model." />
                      </label>
                    </div>

                    <template v-if="activeManager !== 'stimma'">
                      <div class="grid gap-3 sm:grid-cols-2">
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Display name</span>
                          <input v-model="model.name" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-blue-500 focus:outline-none" />
                        </label>
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Context window</span>
                          <input v-model.number="model.max_context_tokens" type="number" min="1024" step="1024" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-blue-500 focus:outline-none" />
                        </label>
                      </div>
                      <label class="flex items-center gap-2 text-xs text-content-secondary">
                        <input v-model="model.supports_tools" type="checkbox" class="rounded border-edge bg-surface" />
                        Tool calls
                      </label>

                      <div v-if="isFlexibleProvider(activeProvider)" class="rounded-lg border border-edge p-3">
                        <div class="flex items-start justify-between gap-4">
                          <div>
                            <div class="text-xs font-medium text-content">Reasoning control</div>
                            <div class="mt-0.5 text-[11px] text-content-muted">Testing can detect how this model toggles thinking.</div>
                          </div>
                          <div class="inline-flex overflow-hidden rounded-md border border-edge text-[11px]">
                            <button type="button" @click="setReasoningSource(model, 'auto')" class="px-2 py-1" :class="model.reasoning_control_source !== 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Auto</button>
                            <button type="button" @click="setReasoningSource(model, 'manual')" class="px-2 py-1" :class="model.reasoning_control_source === 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Manual</button>
                          </div>
                        </div>
                        <div v-if="model.reasoning_control_source !== 'manual'" class="mt-2 text-[11px] text-content-tertiary">Detected: {{ model.reasoning.control || 'none' }}<span v-if="model.detected_runtime"> · {{ model.detected_runtime }}</span></div>
                        <div v-else class="mt-3 grid gap-3 sm:grid-cols-2">
                          <SettingsDropdown control :model-value="model.reasoning.mode" :options="reasoningModeOptions" @update:model-value="setReasoningMode(model, $event)" />
                          <SettingsDropdown control :model-value="model.reasoning.control" :options="reasoningControlOptions" @update:model-value="setReasoningControl(model, $event)" />
                        </div>
                      </div>

                      <div v-if="model.reasoning.mode !== 'none'" class="grid gap-3 sm:grid-cols-2">
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Reasoning levels</span>
                          <input :value="model.reasoning.levels.join(', ')" @change="setReasoningLevels(model, $event.target.value)" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-blue-500 focus:outline-none" />
                        </label>
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Chat default</span>
                          <SettingsDropdown v-model="model.reasoning.default" control :options="model.reasoning.levels.map(level => ({ value: level, label: reasoningLevelLabel(level) }))" />
                        </label>
                      </div>

                      <label v-if="isFlexibleProvider(activeProvider)" class="block">
                        <span class="mb-1 block text-[11px] text-content-tertiary">Extra request body · JSON</span>
                        <textarea :value="extraBodyText(model)" @input="setExtraBody(model, $event.target.value)" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 font-mono text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="{}" />
                        <span v-if="extraBodyErrors[model.id]" class="mt-1 block text-[11px] text-red-400">Invalid JSON object</span>
                      </label>
                    </template>

                    <button type="button" @click="saveModelSettings(model)" :disabled="managerSaving || Boolean(extraBodyErrors[model.id])" class="rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400 disabled:opacity-50">{{ managerSaving ? 'Saving…' : 'Save model settings' }}</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeManager !== 'stimma' && activeProvider" class="flex justify-end border-t border-edge px-5 py-3">
            <button type="button" @click="removeProvider(activeProvider)" class="inline-flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300">
              <TrashIcon /> Delete provider
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Existing local endpoint: preserve the proven endpoint workflow. -->
    <Teleport to="body">
      <div v-if="legacyOpen" class="fixed inset-0 z-[10020] flex items-center justify-center bg-overlay-backdrop p-4 backdrop-blur-sm" @click.self="closeLegacyProvider" @keydown.escape.stop="closeLegacyProvider">
        <div class="flex max-h-[90vh] w-[720px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-xl border border-edge bg-surface shadow-2xl">
          <div class="flex items-start justify-between border-b border-edge px-5 py-4">
            <div class="min-w-0">
              <h4 class="truncate text-base font-medium text-content">{{ legacyDraft.model || legacyProvider?.name }}</h4>
              <p class="mt-0.5 truncate text-xs text-content-tertiary">{{ legacyDraft.url }}</p>
            </div>
            <button type="button" @click="closeLegacyProvider" class="text-sm text-content-muted hover:text-content">Done</button>
          </div>
          <div class="space-y-4 overflow-y-auto p-5">
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="block sm:col-span-2">
                <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                <input v-model="legacyDraft.url" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">API key <span class="text-content-muted">(optional)</span></span>
                <input v-model="legacyKeyDraft" type="password" autocomplete="off" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" :placeholder="legacyDraft.api_key_set ? 'Leave blank to keep current key' : 'Leave empty if not required'" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Model</span>
                <SettingsDropdown v-if="legacyModels.length" v-model="legacyDraft.model" control :options="legacyModels.map(model => ({ value: model, label: model }))" @update:model-value="scheduleLegacyProbe" />
                <input v-else v-model="legacyDraft.model" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" />
              </label>
            </div>

            <div class="rounded-lg border border-edge p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="text-xs">
                  <span v-if="legacyTesting" class="text-content-secondary">Testing…</span>
                  <span v-else-if="legacyDraft.last_test_passed" class="text-green-500">Ready</span>
                  <span v-else-if="legacyDraft.last_tested_at" class="text-red-400">{{ legacyTestError || 'Last test failed' }}</span>
                  <span v-else class="text-content-muted">Not tested yet</span>
                  <span v-if="legacyDraft.last_tested_at" class="ml-1 text-content-muted">· {{ timeAgo(legacyDraft.last_tested_at) }}</span>
                </div>
                <button type="button" @click="runLegacyTest" :disabled="legacyTesting || !legacyDraft.url || !legacyDraft.model" class="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50">{{ legacyDraft.last_tested_at ? 'Re-test' : 'Test connection' }}</button>
              </div>
              <div v-if="legacyScenarios" class="mt-2 flex flex-wrap gap-1.5">
                <span v-for="(result, name) in legacyScenarios" :key="name" class="rounded-md border px-1.5 py-0.5 text-[11px]" :class="result.passed ? 'border-green-500/30 text-green-500' : 'border-red-500/30 text-red-400'">{{ result.passed ? '✓' : '×' }} {{ name }}<span v-if="result.elapsed_ms" class="text-content-muted"> · {{ fmtMs(result.elapsed_ms) }}</span></span>
              </div>
            </div>

            <div class="rounded-lg border border-edge p-3">
              <div class="text-xs font-medium text-content">Prompt policy</div>
              <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                <input v-model="legacyDraft.content_policy_enabled" :value="true" type="radio" class="mt-0.5" />
                <span><span class="block text-xs text-content">Stimma content policy</span><span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Stating the policy typically increases permissiveness and creative control with aligned models, while making refusals clearer.</span></span>
              </label>
              <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                <input v-model="legacyDraft.content_policy_enabled" :value="false" type="radio" class="mt-0.5" />
                <span><span class="block text-xs text-content">Model default</span><span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Do not add Stimma's policy prompt. The model's built-in policy remains in effect.</span></span>
              </label>
              <label class="mt-3 block">
                <span class="mb-1 block text-[11px] text-content-tertiary">Additional instructions</span>
                <textarea v-model="legacyDraft.extra_system_prompt" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="Appended to the system prompt for this model." />
              </label>
            </div>

            <div class="rounded-lg border border-edge p-3">
              <div class="flex items-start justify-between gap-4">
                <div><div class="text-xs font-medium text-content">Reasoning control</div><div class="mt-0.5 text-[11px] text-content-muted">How thinking is toggled per request.</div></div>
                <div class="inline-flex overflow-hidden rounded-md border border-edge text-[11px]">
                  <button type="button" @click="setLegacyReasoningSource('auto')" class="px-2 py-1" :class="legacyDraft.reasoning_method_source !== 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Auto</button>
                  <button type="button" @click="setLegacyReasoningSource('manual')" class="px-2 py-1" :class="legacyDraft.reasoning_method_source === 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Manual</button>
                </div>
              </div>
              <div v-if="legacyDraft.reasoning_method_source !== 'manual'" class="mt-2 text-[11px] text-content-tertiary">Detected: {{ legacyDraft.reasoning_method || 'none' }}<span v-if="legacyDraft.detected_runtime"> · {{ legacyDraft.detected_runtime }}</span></div>
              <SettingsDropdown v-else v-model="legacyDraft.reasoning_method" control class="mt-3" :options="legacyReasoningOptions" />
            </div>

            <div class="rounded-lg border border-edge p-3">
              <div class="mb-1 flex items-baseline justify-between"><label class="text-xs font-medium text-content">Context window</label><span class="text-xs tabular-nums text-content-secondary">{{ Math.round(legacyDraft.max_context_tokens / 1024) }}k tokens</span></div>
              <input v-model.number="legacyDraft.max_context_tokens" type="range" min="32768" max="262144" step="32768" class="w-full accent-blue-500" />
              <p class="mt-1 text-[11px] text-content-muted">Match the model's configured context length. Stimma compacts history at about 80% of this.</p>
            </div>

            <label class="block rounded-lg border border-edge p-3">
              <span class="text-xs font-medium text-content">Extra request body</span>
              <span class="mb-2 mt-0.5 block text-[11px] text-content-muted">Merged into every request for this model.</span>
              <textarea v-model="legacyExtraBodyText" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 font-mono text-xs text-content focus:border-blue-500 focus:outline-none" placeholder='{ "repetition_penalty": 1.05 }' />
              <span v-if="legacyExtraBodyError" class="mt-1 block text-[11px] text-red-400">{{ legacyExtraBodyError }}</span>
            </label>
          </div>
          <div class="flex justify-end border-t border-edge px-5 py-4">
            <button type="button" @click="saveLegacyEndpoint" :disabled="legacySaving || Boolean(legacyExtraBodyError)" class="rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-400 disabled:opacity-50">{{ legacySaving ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import { useAvailableModels } from '../../../composables/useAvailableModels'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import { VOICE_MODELS, voiceModel, isModelReady, supported as voiceSupported } from '../../../composables/useVoiceInput'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'

const ChevronIcon = defineComponent({
  props: { open: Boolean },
  setup(props) {
    return () => h('svg', { class: ['h-4 w-4 shrink-0 text-content-muted transition-transform', props.open ? 'rotate-90' : ''], fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.5' }, [h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'm9 5 7 7-7 7' })])
  },
})
const TrashIcon = defineComponent({
  setup() {
    return () => h('svg', { class: 'h-3.5 w-3.5', fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.5' }, [h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'm14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166M4.772 5.79l1.068 13.133A2.25 2.25 0 0 0 8.084 21h7.832a2.25 2.25 0 0 0 2.244-2.077L19.228 5.79M9.75 5.393V4.477c0-1.18.91-2.164 2.09-2.201a51.964 51.964 0 0 1 3.32 0c1.18.037 2.09 1.022 2.09 2.201v.916' })])
  },
})

const props = defineProps({ llmSettings: { type: Array, default: () => [] } })

const providerKinds = [
  { id: 'openai', name: 'OpenAI', description: 'Use your OpenAI API key.' },
  { id: 'anthropic', name: 'Anthropic', description: 'Use your Anthropic API key.' },
  { id: 'xai', name: 'xAI', description: 'Use your xAI API key for Grok.' },
  { id: 'openrouter', name: 'OpenRouter', description: 'Choose models from your OpenRouter account.' },
  { id: 'local', name: 'Local endpoint', description: 'Connect to LM Studio, vLLM, llama.cpp, Ollama, or another compatible server.' },
]
const reasoningModeOptions = [
  { value: 'none', label: 'Always on / no control' },
  { value: 'optional', label: 'Optional' },
  { value: 'required', label: 'Always on' },
]
const reasoningControlOptions = [
  { value: 'none', label: 'No request control' },
  { value: 'openai_effort', label: 'reasoning_effort' },
  { value: 'openrouter_effort', label: 'OpenRouter reasoning' },
  { value: 'fireworks_effort', label: 'Fireworks reasoning_effort' },
  { value: 'enable_thinking', label: 'enable_thinking' },
  { value: 'think', label: 'think (Ollama)' },
  { value: 'reasoning_budget', label: 'reasoning_budget (llama.cpp)' },
]
const legacyReasoningOptions = [
  { value: 'reasoning_effort', label: 'reasoning_effort' },
  { value: 'openrouter', label: 'reasoning (OpenRouter)' },
  { value: 'enable_thinking', label: 'enable_thinking' },
  { value: 'think', label: 'think (Ollama)' },
  { value: 'reasoning_budget', label: 'reasoning_budget (llama.cpp)' },
  { value: 'none', label: 'Always on / no control' },
]

const { models, quickTaskModel, cloudStatus, cloudMessage, fetchModels, invalidateCache } = useAvailableModels()
const { privacyLockdownActive } = usePrivacyLockdown()
const providers = ref([])
const voiceModelReady = ref(false)
const modelPrompts = ref({})

const cloudModels = computed(() => models.value.filter(model => model.source === 'stimma_cloud'))
const selectedQuickModel = computed(() => models.value.find(model => model.slug === quickTaskModel.value))
const quickTaskOptions = computed(() => models.value.filter(model => model.source !== 'auto' && !model.collapsed && (model.available !== false || model.slug === quickTaskModel.value)).map(model => ({
  value: model.slug,
  label: model.name,
  description: `via ${model.source === 'stimma_cloud' ? 'Stimma' : (model.provider_name || endpointHost(model.endpoint_url) || 'your endpoint')}`,
  meta: model.cost_tier || '',
  tone: model.source === 'stimma_cloud' ? 'cloud' : undefined,
  disabled: model.available === false,
})))
const voiceModelOptions = computed(() => VOICE_MODELS.map(model => ({
  value: model.id,
  label: model.label,
  description: model.size,
})))

const legacyOverride = ref(null)
const legacyEndpoint = computed(() => {
  if (legacyOverride.value) return legacyOverride.value
  return props.llmSettings.find(item => item.role === 'agent')?.endpoint || null
})
const legacyProvider = computed(() => {
  const endpoint = legacyEndpoint.value
  if (!endpoint?.url) return null
  let host = endpoint.url
  try { host = new URL(endpoint.url).host || endpoint.url } catch {}
  return { name: endpoint.detected_runtime ? `${endpoint.detected_runtime} · ${host}` : host, model: endpoint.model || 'Configured model', ...endpoint }
})

function kindLabel(kind) { return providerKinds.find(item => item.id === kind)?.name || kind }
function kindDescription(kind) { return providerKinds.find(item => item.id === kind)?.description || '' }
function endpointHost(url) {
  if (!url) return ''
  try { return new URL(url).host } catch { return url }
}
function modelSummary(items) {
  const names = items.map(item => item.name || item.model_id).filter(Boolean)
  if (!names.length) return 'No models selected'
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} +${names.length - 3}` : names.join(', ')
}
function modelKey(model) { return model.slug || model.id }
function modelVendor(model) {
  const raw = model.upstream_provider || model.provider_kind || model.canonical_model_id?.split(':')[0]
  const labels = { openai: 'OpenAI', anthropic: 'Anthropic', xai: 'xAI', minimax: 'MiniMax', qwen: 'Qwen', stepfun: 'StepFun', moonshot: 'Moonshot AI', fireworks: 'Fireworks', openrouter: 'OpenRouter', local: 'Local endpoint' }
  return labels[raw] || (activeProvider.value ? kindLabel(activeProvider.value.kind) : 'Model provider')
}
function timeAgo(iso) {
  if (!iso) return ''
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}
function fmtMs(ms) { return ms > 999 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms` }
function clone(value) { return JSON.parse(JSON.stringify(value)) }

async function loadProviders() {
  const response = await axios.get(`${getApiBase()}/models/providers`)
  providers.value = response.data.providers || []
}
async function loadPromptSettings() {
  const response = await axios.get(`${getApiBase()}/settings`)
  modelPrompts.value = response.data.llm_model_prompts || {}
}
async function refreshAll() {
  invalidateCache()
  await Promise.all([fetchModels(null, true), loadProviders(), loadPromptSettings()])
}
async function saveQuickTaskModel(model) {
  await axios.patch(`${getApiBase()}/settings/quick-task-model`, { model })
  await fetchModels(null, true)
}

// Add provider dialog
const addOpen = ref(false)
const addStep = ref('connection')
const addDraft = ref({ kind: '', name: '', base_url: '', api_key: '' })
const addDiscoveredModels = ref([])
const addSelectedModels = ref(new Set())
const addSaving = ref(false)
const addError = ref('')

function openAddProvider() {
  addDraft.value = { kind: '', name: '', base_url: '', api_key: '' }
  addStep.value = 'connection'
  addDiscoveredModels.value = []
  addSelectedModels.value = new Set()
  addError.value = ''
  addOpen.value = true
}
function closeAddProvider() { addOpen.value = false }
function selectProviderKind(kind) {
  addDraft.value = { kind, name: '', base_url: kind === 'local' ? 'http://localhost:1234/v1' : '', api_key: '' }
  addStep.value = 'connection'
  addError.value = ''
}
function backAddProvider() {
  if (addStep.value === 'models') addStep.value = 'connection'
  else addDraft.value.kind = ''
}
function toggleAddModel(id) {
  const next = new Set(addSelectedModels.value)
  next.has(id) ? next.delete(id) : next.add(id)
  addSelectedModels.value = next
}
async function advanceAddProvider() {
  addSaving.value = true
  addError.value = ''
  try {
    if (addStep.value === 'connection' && ['openrouter', 'local'].includes(addDraft.value.kind)) {
      const response = await axios.post(`${getApiBase()}/models/providers/discover`, addDraft.value)
      addDiscoveredModels.value = response.data.models || []
      addSelectedModels.value = new Set(addDiscoveredModels.value.length === 1 ? [addDiscoveredModels.value[0].id] : [])
      addStep.value = 'models'
      return
    }
    const payload = { ...addDraft.value, model_ids: [...addSelectedModels.value] }
    const response = await axios.post(`${getApiBase()}/models/providers`, payload)
    await refreshAll()
    closeAddProvider()
    openProvider(response.data)
  } catch (error) {
    addError.value = error.response?.data?.detail || 'Could not add this provider.'
  } finally {
    addSaving.value = false
  }
}

// Provider manager
const managerOpen = ref(false)
const activeManager = ref(null)
const activeProvider = ref(null)
const providerKeyDraft = ref('')
const managerSaving = ref(false)
const managerError = ref('')
const testingId = ref(null)
const discoveredModels = ref([])
const selectedManagerIds = ref(new Set())
const customizingModelId = ref(null)
const extraBodyDrafts = ref({})
const extraBodyErrors = ref({})

const managerTitle = computed(() => activeManager.value === 'stimma' ? 'Stimma Account' : activeProvider.value?.name || '')
const managerSubtitle = computed(() => activeManager.value === 'stimma'
  ? (cloudStatus.value === 'available' ? `${cloudModels.value.length} models · billed through Stimma` : cloudMessage.value || 'Unavailable')
  : activeProvider.value ? `${kindLabel(activeProvider.value.kind)} · ${activeProvider.value.models.length} models` : '')
const managerModels = computed(() => activeManager.value === 'stimma' ? cloudModels.value : (activeProvider.value?.models || []))

function openStimmaAccount() {
  activeManager.value = 'stimma'
  activeProvider.value = null
  customizingModelId.value = null
  managerOpen.value = true
}
function openProvider(provider) {
  activeManager.value = provider.id
  activeProvider.value = clone(provider)
  providerKeyDraft.value = ''
  managerError.value = ''
  customizingModelId.value = null
  discoveredModels.value = []
  selectedManagerIds.value = new Set(provider.models.filter(model => model.enabled).map(model => model.model_id))
  extraBodyDrafts.value = Object.fromEntries(provider.models.map(model => [model.id, JSON.stringify(model.extra_body || {}, null, 2)]))
  extraBodyErrors.value = {}
  managerOpen.value = true
}
function closeManager() { managerOpen.value = false }
function isFlexibleProvider(provider) { return provider && ['openrouter', 'local'].includes(provider.kind) }
function toggleModelSettings(model) { customizingModelId.value = customizingModelId.value === modelKey(model) ? null : modelKey(model) }
function modelPrompt(model) {
  if (activeManager.value === 'stimma') {
    if (!modelPrompts.value[model.slug]) modelPrompts.value[model.slug] = { content_policy_enabled: true, extra_system_prompt: '' }
    return modelPrompts.value[model.slug]
  }
  if (model.content_policy_enabled == null) model.content_policy_enabled = true
  if (model.extra_system_prompt == null) model.extra_system_prompt = ''
  return model
}
async function saveModelSettings(model) {
  managerSaving.value = true
  managerError.value = ''
  try {
    if (activeManager.value === 'stimma') {
      const prompt = modelPrompt(model)
      await axios.patch(`${getApiBase()}/settings/model-prompt`, { model: model.slug, ...prompt })
    } else {
      const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, { models: activeProvider.value.models })
      activeProvider.value = clone(response.data)
      await loadProviders()
    }
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not save model settings.'
  } finally {
    managerSaving.value = false
  }
}
async function saveProviderConnection() {
  managerSaving.value = true
  managerError.value = ''
  try {
    const payload = { name: activeProvider.value.name, base_url: activeProvider.value.base_url }
    if (providerKeyDraft.value) payload.api_key = providerKeyDraft.value
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, payload)
    activeProvider.value = clone(response.data)
    providerKeyDraft.value = ''
    await loadProviders()
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not save this connection.'
  } finally {
    managerSaving.value = false
  }
}
async function testProvider(provider) {
  testingId.value = provider.id
  managerError.value = ''
  try {
    await axios.post(`${getApiBase()}/models/providers/${provider.id}/test`)
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'The test failed.'
  } finally {
    testingId.value = null
    await loadProviders()
    const refreshed = providers.value.find(item => item.id === provider.id)
    if (refreshed) activeProvider.value = clone(refreshed)
  }
}
async function loadProviderModels(provider) {
  managerError.value = ''
  try {
    const response = await axios.get(`${getApiBase()}/models/providers/${provider.id}/models`)
    discoveredModels.value = response.data.models || []
    selectedManagerIds.value = new Set(discoveredModels.value.filter(model => model.selected).map(model => model.id))
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not load models.'
  }
}
function toggleManagerModel(id) {
  const next = new Set(selectedManagerIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedManagerIds.value = next
}
async function saveProviderModels() {
  managerSaving.value = true
  try {
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, { model_ids: [...selectedManagerIds.value] })
    activeProvider.value = clone(response.data)
    await refreshAll()
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not save shown models.'
  } finally {
    managerSaving.value = false
  }
}
async function removeProvider(provider) {
  await axios.delete(`${getApiBase()}/models/providers/${provider.id}`)
  closeManager()
  await refreshAll()
}

function setReasoningSource(model, source) {
  model.reasoning_control_source = source
  if (source === 'manual' && !model.reasoning.control) model.reasoning.control = 'openai_effort'
}
function setReasoningMode(model, mode) { model.reasoning.mode = mode; normalizeReasoning(model) }
function setReasoningControl(model, control) { model.reasoning.control = control; normalizeReasoning(model) }
function reasoningLevelLabel(level) { return level === 'off' ? 'Off' : level === 'xhigh' ? 'XHigh' : level }
function wireLevelsFor(model) {
  return Object.fromEntries(model.reasoning.levels.map((level, index) => {
    if (['enable_thinking', 'think'].includes(model.reasoning.control)) return [level, level !== 'off']
    if (model.reasoning.control === 'reasoning_budget') return [level, level === 'off' ? 0 : [1024, 4096, 16384, 32768][Math.min(index, 3)]]
    if (['openai_effort', 'fireworks_effort', 'openrouter_effort'].includes(model.reasoning.control)) return [level, level === 'off' ? 'none' : level]
    return [level, level]
  }))
}
function normalizeReasoning(model) {
  if (model.reasoning.mode === 'none') {
    model.reasoning.levels = ['off']; model.reasoning.default = 'off'; model.reasoning.quick_task = 'off'; model.reasoning.control = 'none'
  } else if (!model.reasoning.levels.length || (model.reasoning.levels.length === 1 && model.reasoning.levels[0] === 'off')) {
    model.reasoning.levels = model.reasoning.mode === 'required' ? ['low', 'medium', 'high'] : ['off', 'low', 'medium', 'high']
    model.reasoning.default = 'medium'; model.reasoning.quick_task = model.reasoning.levels[0]
  }
  model.reasoning.wire_levels = wireLevelsFor(model)
}
function setReasoningLevels(model, value) {
  model.reasoning.levels = [...new Set(value.split(',').map(level => level.trim().toLowerCase()).filter(Boolean))] || ['off']
  if (!model.reasoning.levels.length) model.reasoning.levels = ['off']
  if (!model.reasoning.levels.includes(model.reasoning.default)) model.reasoning.default = model.reasoning.levels[0]
  model.reasoning.quick_task = model.reasoning.levels[0]
  model.reasoning.wire_levels = wireLevelsFor(model)
}
function extraBodyText(model) { return extraBodyDrafts.value[model.id] ?? JSON.stringify(model.extra_body || {}, null, 2) }
function setExtraBody(model, value) {
  extraBodyDrafts.value = { ...extraBodyDrafts.value, [model.id]: value }
  try {
    const parsed = value.trim() ? JSON.parse(value) : null
    if (parsed != null && (typeof parsed !== 'object' || Array.isArray(parsed))) throw new Error()
    model.extra_body = parsed
    const errors = { ...extraBodyErrors.value }; delete errors[model.id]; extraBodyErrors.value = errors
  } catch { extraBodyErrors.value = { ...extraBodyErrors.value, [model.id]: true } }
}

// Existing endpoint manager, retaining the old tested behavior.
const legacyOpen = ref(false)
const legacyDraft = ref({})
const legacyKeyDraft = ref('')
const legacyModels = ref([])
const legacyScenarios = ref(null)
const legacyTesting = ref(false)
const legacySaving = ref(false)
const legacyTestError = ref('')
const legacyExtraBodyText = ref('')
let legacyProbeTimer = null
const legacyExtraBodyError = computed(() => {
  if (!legacyExtraBodyText.value.trim()) return ''
  try {
    const parsed = JSON.parse(legacyExtraBodyText.value)
    return typeof parsed === 'object' && !Array.isArray(parsed) ? '' : 'Must be a JSON object'
  } catch { return 'Invalid JSON' }
})
function openLegacyProvider() {
  legacyDraft.value = clone(legacyEndpoint.value)
  legacyKeyDraft.value = ''
  legacyExtraBodyText.value = legacyDraft.value.extra_body ? JSON.stringify(legacyDraft.value.extra_body, null, 2) : ''
  legacyScenarios.value = null
  legacyTestError.value = ''
  legacyOpen.value = true
  fetchLegacyModels()
}
function closeLegacyProvider() { clearTimeout(legacyProbeTimer); legacyOpen.value = false }
async function fetchLegacyModels() {
  if (!legacyDraft.value.url) return
  try {
    const body = { url: legacyDraft.value.url }
    if (legacyKeyDraft.value) body.api_key = legacyKeyDraft.value
    const response = await axios.post(`${getApiBase()}/settings/llms/endpoint/models`, body)
    legacyModels.value = response.data.models || []
    if (legacyModels.value.length && !legacyModels.value.includes(legacyDraft.value.model)) legacyDraft.value.model = legacyModels.value[0]
  } catch { legacyModels.value = [] }
}
function legacyPayload() {
  const payload = {
    endpoint_url: legacyDraft.value.url || '', endpoint_model: legacyDraft.value.model || '',
    endpoint_max_context_tokens: legacyDraft.value.max_context_tokens || 131072,
    endpoint_content_policy_enabled: legacyDraft.value.content_policy_enabled !== false,
    endpoint_extra_system_prompt: legacyDraft.value.extra_system_prompt || '',
    endpoint_extra_body: legacyExtraBodyText.value.trim() ? JSON.parse(legacyExtraBodyText.value) : {},
    endpoint_reasoning_method: legacyDraft.value.reasoning_method || '',
    endpoint_reasoning_method_source: legacyDraft.value.reasoning_method_source || 'auto',
  }
  if (legacyKeyDraft.value) payload.endpoint_api_key = legacyKeyDraft.value
  return payload
}
async function saveLegacyEndpoint() {
  if (legacyExtraBodyError.value) return
  legacySaving.value = true
  try {
    const payload = legacyPayload()
    const [agent] = await Promise.all([
      axios.patch(`${getApiBase()}/settings/llms/agent`, payload),
      axios.patch(`${getApiBase()}/settings/llms/agent-fast`, payload),
    ])
    legacyOverride.value = clone(agent.data.endpoint)
    legacyDraft.value = clone(agent.data.endpoint)
    legacyKeyDraft.value = ''
    invalidateCache()
    await fetchModels(null, true)
  } finally { legacySaving.value = false }
}
async function runLegacyTest() {
  clearTimeout(legacyProbeTimer)
  legacyTesting.value = true
  legacyTestError.value = ''
  try {
    await saveLegacyEndpoint()
    const previousModel = legacyDraft.value.model
    await fetchLegacyModels()
    if (legacyDraft.value.model !== previousModel) await saveLegacyEndpoint()
    const response = await axios.post(`${getApiBase()}/settings/llms/agent/test`)
    legacyScenarios.value = response.data.scenarios || null
    legacyDraft.value.last_tested_at = new Date().toISOString()
    legacyDraft.value.last_test_passed = response.data.success
    legacyTestError.value = response.data.error || ''
    if (response.data.detected) {
      legacyDraft.value.detected_runtime = response.data.detected.runtime
      if (legacyDraft.value.reasoning_method_source !== 'manual') legacyDraft.value.reasoning_method = response.data.detected.reasoning_method
    }
    legacyOverride.value = clone(legacyDraft.value)
  } catch (error) {
    legacyDraft.value.last_tested_at = new Date().toISOString()
    legacyDraft.value.last_test_passed = false
    legacyTestError.value = error.response?.data?.detail || 'Connection test failed'
  } finally { legacyTesting.value = false }
}
function scheduleLegacyProbe() {
  clearTimeout(legacyProbeTimer)
  if (!legacyDraft.value.url) return
  legacyProbeTimer = setTimeout(runLegacyTest, 700)
}
function setLegacyReasoningSource(source) {
  legacyDraft.value.reasoning_method_source = source
  if (source === 'manual' && !legacyDraft.value.reasoning_method) legacyDraft.value.reasoning_method = 'reasoning_effort'
}

async function refreshVoiceModelReady() { voiceModelReady.value = await isModelReady(voiceModel.value) }
watch(voiceModel, refreshVoiceModelReady)
onMounted(async () => { await refreshVoiceModelReady(); await refreshAll() })
</script>
