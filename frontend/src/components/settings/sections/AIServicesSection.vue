<template>
  <div class="space-y-6">
    <template v-if="!addOpen && !managerOpen && !legacyOpen">
    <section>
      <div v-if="!wizard" class="mb-3">
        <div class="flex items-center gap-3">
          <h3 class="text-base font-medium text-content">Chat Models</h3>
        </div>
        <p class="mt-1 text-xs text-content-tertiary">Choose models from your Stimma account, API providers, or your own endpoints.</p>
      </div>

      <div
        v-if="setupRequired && !wizard"
        class="mb-5 flex w-full items-center gap-3 rounded-lg border border-yellow-400/30 bg-yellow-400/10 px-4 py-3"
      >
        <span class="h-2 w-2 shrink-0 rounded-full bg-yellow-400"></span>
        <p class="text-sm text-content-secondary">Connect a chat model to use chat, the agent, and AI-assisted features.</p>
      </div>

      <div class="space-y-0.5">
        <button type="button" class="group flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-overlay-subtle" @click="cloudStatus === 'not_logged_in' ? handleCloudConnect() : cloudNeedsCredits ? openAddCredits() : openStimmaAccount()">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary" aria-hidden="true">
            <div class="h-7 w-7 bg-current [mask-image:url('/logo.png')] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url('/logo.png')] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]"></div>
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-content">Stimma</div>
            <div v-if="cloudStatus === 'available' || cloudStatus === 'not_logged_in'" class="mt-0.5 truncate text-xs text-content-tertiary">Use a variety of models with one pool of credits.</div>
            <div v-else-if="cloudMessage" class="mt-1 truncate text-xs text-red-400">{{ cloudMessage }}</div>
            <div v-else-if="cloudConnectError" class="mt-1 truncate text-xs text-red-400">{{ cloudConnectError }}</div>
          </div>
          <template v-if="cloudStatus === 'not_logged_in'">
            <div class="min-w-20 shrink-0 text-right text-xs">
              <span class="relative inline-block">
                <span class="invisible" aria-hidden="true">Configure</span>
                <span class="absolute left-0 top-1/2 -translate-y-1/2 whitespace-nowrap rounded-md bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-3.5 py-1.5 text-xs font-medium text-white transition-all group-hover:from-teal-500 group-hover:via-cyan-400 group-hover:to-indigo-400" :class="{ 'opacity-60': cloudConnecting }">
                  {{ cloudConnecting ? 'Connecting…' : 'Sign in' }}
                </span>
              </span>
            </div>
            <span class="h-4 w-4 shrink-0" aria-hidden="true"></span>
          </template>
          <template v-else>
            <div class="min-w-20 shrink-0 text-right text-xs" :class="cloudStatus !== 'available' ? 'text-red-400' : cloudNeedsCredits ? 'text-yellow-400' : 'text-green-400'">
              {{ cloudStatus !== 'available' ? 'Unavailable' : cloudNeedsCredits ? 'Add credits' : `Ready · ${cloudModels.length} model${cloudModels.length === 1 ? '' : 's'}` }}
            </div>
            <ChevronIcon />
          </template>
        </button>

        <button
          v-for="provider in visibleRemoteProviderRows"
          :key="provider.id || provider.kind"
          type="button"
          @click="openProvider(provider)"
          class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-overlay-subtle"
        >
          <div class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary">
            <ProviderBrandIcon :provider="provider.kind" size="md" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-content">{{ provider.name }}</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ kindDescription(provider.kind) }}</div>
            <div v-if="provider.last_error" class="mt-1 truncate text-xs text-red-400">{{ provider.last_error }}</div>
          </div>
          <div class="min-w-20 shrink-0 text-right text-xs" :class="provider._unconfigured ? 'text-blue-400' : provider.last_test_passed === false ? 'text-red-400' : 'text-content-muted'">
            {{ provider._unconfigured ? 'Configure' : provider.last_test_passed === false ? 'Check failed' : provider.last_test_passed ? `${provider.models.length} model${provider.models.length === 1 ? '' : 's'}` : 'Not checked' }}
          </div>
          <ChevronIcon />
        </button>

        <button
          v-for="provider in localProviders"
          :key="provider.id"
          type="button"
          @click="openProvider(provider)"
          class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-overlay-subtle"
        >
          <div class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary">
            <ProviderBrandIcon provider="local" size="md" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-content">{{ provider.name }}</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ modelSummary(provider.models) }}</div>
            <div v-if="provider.last_error" class="mt-1 truncate text-xs text-red-400">{{ provider.last_error }}</div>
          </div>
          <div class="min-w-20 shrink-0 text-right text-xs" :class="provider.last_test_passed === false ? 'text-red-400' : 'text-content-muted'">
            {{ provider.last_test_passed === false ? 'Check failed' : provider.last_test_passed ? `${provider.models.length} model${provider.models.length === 1 ? '' : 's'}` : 'Not checked' }}
          </div>
          <ChevronIcon />
        </button>

        <button
          v-if="legacyProvider"
          type="button"
          @click="openLegacyProvider"
          class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-overlay-subtle"
        >
          <div class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary">
            <ProviderBrandIcon provider="local" size="md" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-content">{{ legacyProvider.name }}</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">{{ legacyProvider.model }}</div>
          </div>
          <div class="min-w-20 shrink-0 text-right text-xs" :class="legacyProvider.last_test_passed === false ? 'text-red-400' : 'text-content-muted'">
            {{ legacyProvider.last_test_passed === false ? 'Check failed' : legacyProvider.last_test_passed ? '1 model' : 'Not checked' }}
          </div>
          <ChevronIcon />
        </button>

        <button type="button" @click="openAddLocalProvider" class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-blue-500/[0.04]">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center text-blue-400">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-blue-400">Add OpenAI Compatible Endpoint</div>
            <div class="mt-0.5 truncate text-xs text-content-tertiary">Connect LM Studio, vLLM, llama.cpp, Ollama, or another compatible server.</div>
          </div>
        </button>
      </div>

      <div v-if="wizard && hiddenRemoteProviderCount > 0" class="mt-3 px-1">
        <button type="button" class="text-xs text-content-tertiary hover:text-content-secondary hover:underline" @click="showAllProviders = true">See all</button>
      </div>
    </section>

    </template>

    <!-- Add OpenAI-compatible endpoint -->
    <div v-else-if="addOpen" class="-m-6 min-h-full" @keydown.escape.stop="closeAddProvider">
          <div class="flex items-center gap-3 px-6 pb-2 pt-4">
            <button type="button" @click="closeAddProvider" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-content-secondary hover:bg-overlay-subtle hover:text-content">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
            </button>
            <div>
              <h4 class="text-base font-medium text-content">Add OpenAI Compatible Endpoint</h4>
              <p class="mt-0.5 text-xs text-content-tertiary">{{ kindDescription('local') }}</p>
            </div>
          </div>

          <div class="px-6 py-4">
            <div class="space-y-4">
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Name <span class="text-content-muted">(optional)</span></span>
                <input v-model="addDraft.name" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" placeholder="Studio Mac" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                <input v-model="addDraft.base_url" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" placeholder="http://localhost:1234/v1" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">API key <span class="text-content-muted">(optional)</span></span>
                <input v-model="addDraft.api_key" type="password" autocomplete="off" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" placeholder="Leave empty if not required" />
              </label>
            </div>

            <p v-if="addError" class="mt-4 text-xs text-red-400">{{ addError }}</p>
          </div>

          <div class="flex items-center justify-between px-6 pb-4 pt-2">
            <button type="button" @click="closeAddProvider" class="text-xs text-content-secondary hover:text-content">Cancel</button>
            <button type="button" @click="advanceAddProvider" :disabled="addSaving" class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">
              {{ addSaving ? 'Checking…' : 'Continue' }}
            </button>
          </div>
    </div>

    <!-- Provider settings -->
    <div v-else-if="managerOpen" class="-m-6 min-h-full" @keydown.escape.stop="managerBack">
          <div class="flex items-center gap-3 px-6 pb-2 pt-4">
            <button type="button" @click="managerBack" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-content-secondary hover:bg-overlay-subtle hover:text-content">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
            </button>
            <div v-if="selectedManagerModel" class="flex min-w-0 flex-1 items-center gap-3">
              <div class="flex items-center gap-3">
                <ModelVendorIcon :model="selectedManagerModel" size="md" />
                <div class="min-w-0">
                  <h4 class="truncate text-base font-medium text-content">{{ selectedManagerModel.name }}</h4>
                  <p class="mt-0.5 text-xs text-content-tertiary">{{ modelVendor(selectedManagerModel) }}<span v-if="selectedManagerModel.cost_tier"> · {{ selectedManagerModel.cost_tier }}</span></p>
                </div>
              </div>
            </div>
            <div v-else class="flex min-w-0 flex-1 items-center gap-3">
              <div v-if="activeProvider || activeManager === 'stimma'" class="flex h-9 w-9 shrink-0 items-center justify-center text-content-secondary" :aria-hidden="activeManager === 'stimma' ? true : undefined">
                <ProviderBrandIcon v-if="activeProvider" :provider="activeProvider.kind" size="md" />
                <div v-else class="h-7 w-7 bg-current [mask-image:url('/logo.png')] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url('/logo.png')] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]"></div>
              </div>
              <div class="min-w-0">
                <h4 class="truncate text-base font-medium text-content">{{ modelAddStep === 'choose' ? 'Add a model' : managerTitle }}</h4>
              </div>
            </div>
          </div>

          <div ref="managerBody" class="p-6">
            <div v-if="modelAddStep === 'choose'" class="space-y-3">
              <input v-model="modelSearch" type="search" autofocus placeholder="Search models…" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content placeholder:text-content-muted focus:border-accent focus:outline-none" />
              <div v-if="managerLoadingModels" class="py-10 text-center text-sm text-content-muted">Loading models…</div>
              <div v-else-if="availableProviderModels.length" class="space-y-0.5">
                <button v-for="model in availableProviderModels" :key="model.id" type="button" @click="chooseProviderModel(model)" class="flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-overlay-subtle">
                  <ModelVendorIcon :model="model" size="md" />
                  <div class="min-w-0 flex-1"><div class="truncate text-sm font-medium text-content">{{ model.name }}</div><div class="mt-0.5 truncate text-[11px] text-content-muted">{{ model.id }}</div></div>
                  <ChevronIcon />
                </button>
              </div>
              <p v-else class="py-10 text-center text-sm text-content-muted">{{ modelSearch ? 'No matching models.' : 'No more models are available.' }}</p>
              <p v-if="managerError" class="text-xs text-red-400">{{ managerError }}</p>
            </div>

            <template v-else>
            <template v-if="!selectedManagerModel && activeManager !== 'stimma' && activeProvider">
              <section v-if="isRemoteProvider(activeProvider)" class="max-w-2xl">
                <h5 class="text-sm font-medium text-content">API key</h5>
                <p class="mt-1 text-xs leading-relaxed text-content-tertiary">
                  {{ activeProviderKind?.apiKeyHelp }}
                  <button type="button" @click="openProviderKeyPage" class="ml-1 text-blue-400 hover:text-blue-300 hover:underline">Get an API key ↗</button>
                </p>
                <div v-if="activeProvider.api_key_set && !editingProviderKey" class="mt-4 flex items-center gap-2">
                  <input type="text" value="••••••••••••••••" disabled aria-label="Saved API key" class="min-w-0 flex-1 cursor-not-allowed rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm tracking-wider text-content-muted opacity-70" />
                  <button type="button" @click="beginProviderKeyEdit" class="rounded-md px-3 py-2 text-sm text-blue-400 hover:bg-overlay-subtle hover:text-blue-300">Change key</button>
                </div>
                <div v-else class="mt-4 flex items-center gap-2">
                  <input v-model="providerKeyDraft" type="password" autocomplete="off" class="min-w-0 flex-1 rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" :placeholder="activeProvider.api_key_set ? '••••••••••••' : 'Paste API key'" />
                  <button type="button" @click="saveProviderConnection" :disabled="managerSaving || !providerKeyDraft" class="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">{{ activeProvider.api_key_set ? 'Save' : 'Connect' }}</button>
                  <button v-if="activeProvider.api_key_set" type="button" @click="cancelProviderKeyEdit" :disabled="managerSaving" class="rounded-md px-3 py-2 text-sm text-content-secondary hover:bg-overlay-subtle hover:text-content disabled:opacity-50">Cancel</button>
                </div>
                <p v-if="managerError" class="mt-2 text-xs text-red-400">{{ managerError }}</p>
              </section>

              <div v-else class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-xs text-content-tertiary">Name</span>
                  <input v-model="activeProvider.name" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
                </label>
                <label class="block">
                  <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                  <input v-model="activeProvider.base_url" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
                </label>
                <label class="block sm:col-span-2">
                  <span class="mb-1 block text-xs text-content-tertiary">API key <span class="text-content-muted">(optional)</span></span>
                  <input v-model="providerKeyDraft" type="password" autocomplete="off" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" :placeholder="activeProvider.api_key_set ? 'Leave blank to keep the current key' : 'Leave empty if not required'" />
                </label>
              </div>
              <div v-if="!isRemoteProvider(activeProvider)" class="mt-3 flex items-center gap-3">
                <button type="button" @click="saveProviderConnection" :disabled="managerSaving" class="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">{{ managerSaving ? 'Checking…' : 'Save connection' }}</button>
                <button type="button" @click="testProvider(activeProvider)" :disabled="testingId === activeProvider.id" class="text-xs text-content-secondary hover:text-content disabled:opacity-50">{{ testingId === activeProvider.id ? 'Testing…' : 'Check connection' }}</button>
                <span v-if="activeProvider.last_tested_at" class="text-[11px] text-content-muted">Tested {{ timeAgo(activeProvider.last_tested_at) }}</span>
              </div>
              <p v-if="managerError && !isRemoteProvider(activeProvider)" class="mt-2 text-xs text-red-400">{{ managerError }}</p>

            </template>

            <div v-if="selectedManagerModel || activeManager === 'stimma' || managerModels.length || (isFlexibleProvider(activeProvider) && !activeProvider?._unconfigured)" :class="!selectedManagerModel && activeManager !== 'stimma' ? 'mt-8' : ''">
              <template v-if="!selectedManagerModel">
                <h5 class="text-sm font-medium text-content">Models</h5>
              </template>
              <div :class="selectedManagerModel ? '' : 'mt-3 space-y-0.5'">
                <div v-for="model in managerPageModels" :key="model.slug || model.id">
                  <component
                    :is="activeManager === 'stimma' ? 'div' : 'button'"
                    v-if="!selectedManagerModel"
                    :type="activeManager === 'stimma' ? undefined : 'button'"
                    @click="activeManager !== 'stimma' && openModelSettings(model)"
                    class="flex w-full items-center gap-3 px-1 py-3 text-left"
                    :class="activeManager === 'stimma' ? '' : 'hover:bg-overlay-subtle'"
                  >
                    <ModelVendorIcon :model="model" size="md" />
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-sm text-content">{{ model.name }}</div>
                      <div class="mt-0.5 text-[11px] text-content-muted">{{ modelVendor(model) }}<span v-if="model.cost_tier"> · {{ model.cost_tier }}</span></div>
                    </div>
                    <span v-if="isFlexibleProvider(activeProvider) && model.last_test_passed === false" class="text-[11px] text-red-400">Failed</span>
                    <span v-else-if="isFlexibleProvider(activeProvider) && model.last_test_passed" class="text-[11px] text-green-500">Ready</span>
                    <ChevronIcon v-if="activeManager !== 'stimma'" />
                  </component>

                  <div v-if="selectedManagerModel" class="space-y-4">
                    <ProviderModelSetup
                      v-if="isFlexibleProvider(activeProvider)"
                      :model="model"
                      :is-new="Boolean(modelSetupDraft)"
                      :testing="managerTestingModel"
                      :saving="managerSaving"
                      :error="managerError"
                      @test="profileManagerModel(model)"
                      @commit="commitProviderModel"
                      @save="saveModelSettings(model)"
                      @remove="removeProviderModel(model)"
                    />
                    <template v-else>
                    <div v-if="activeProvider?.kind === 'local' && model.last_test_results && Object.keys(model.last_test_results).length" class="flex flex-wrap gap-1.5">
                      <span v-for="(result, name) in model.last_test_results" :key="name" class="rounded-md border px-1.5 py-0.5 text-[11px]" :class="result.passed ? 'border-green-500/30 text-green-500' : 'border-red-500/30 text-red-400'">
                        {{ result.passed ? '✓' : '×' }} {{ name }}<span v-if="result.elapsed_ms" class="text-content-muted"> · {{ fmtMs(result.elapsed_ms) }}</span>
                      </span>
                    </div>

                    <div class="py-2">
                      <div class="text-xs font-medium text-content">System prompt policy</div>
                      <p class="mt-1 text-[11px] leading-relaxed text-content-muted">Choose whether Stimma adds its Content Policy to this model's system prompt.</p>
                      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                        <input type="radio" :name="`policy-${modelKey(model)}`" :checked="modelPrompt(model).content_policy_enabled" @change="updateModelPolicy(model, true)" class="mt-0.5" />
                        <span>
                          <span class="block text-xs text-content">Include Stimma's Content Policy</span>
                          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Adds the policy to the system prompt. With aligned models, stating it typically increases permissiveness and creative control while making refusals clearer.</span>
                        </span>
                      </label>
                      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                        <input type="radio" :name="`policy-${modelKey(model)}`" :checked="!modelPrompt(model).content_policy_enabled" @change="updateModelPolicy(model, false)" class="mt-0.5" />
                        <span>
                          <span class="block text-xs text-content">Do not include it</span>
                          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Does not add Stimma's Content Policy to the system prompt. The provider or model's built-in policy remains in effect.</span>
                        </span>
                      </label>
                      <label v-if="isFlexibleProvider(activeProvider)" class="mt-3 block">
                        <span class="mb-1 block text-[11px] text-content-tertiary">Additional instructions</span>
                        <textarea v-model="modelPrompt(model).extra_system_prompt" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-accent focus:outline-none" placeholder="Appended to the system prompt for this model." />
                      </label>
                    </div>

                    <template v-if="isFlexibleProvider(activeProvider)">
                      <div class="grid gap-3 sm:grid-cols-2">
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Display name</span>
                          <input v-model="model.name" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-accent focus:outline-none" />
                        </label>
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Context window</span>
                          <input v-model.number="model.max_context_tokens" type="number" min="1024" step="1024" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-accent focus:outline-none" />
                        </label>
                      </div>
                      <label v-if="isFlexibleProvider(activeProvider)" class="block">
                        <span class="mb-1 block text-[11px] text-content-tertiary">Model maker</span>
                        <SettingsDropdown v-model="model.model_vendor" control :options="modelVendorOptions" />
                      </label>
                      <label class="flex items-center gap-2 text-xs text-content-secondary">
                        <input v-model="model.supports_tools" type="checkbox" class="rounded border-edge bg-surface" />
                        Tool calls
                      </label>

                      <div v-if="isFlexibleProvider(activeProvider)" class="py-2">
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
                          <input :value="model.reasoning.levels.join(', ')" @change="setReasoningLevels(model, $event.target.value)" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-accent focus:outline-none" />
                        </label>
                        <label class="block">
                          <span class="mb-1 block text-[11px] text-content-tertiary">Chat default</span>
                          <SettingsDropdown v-model="model.reasoning.default" control :options="model.reasoning.levels.map(level => ({ value: level, label: reasoningLevelLabel(level) }))" />
                        </label>
                      </div>

                      <label v-if="isFlexibleProvider(activeProvider)" class="block">
                        <span class="mb-1 block text-[11px] text-content-tertiary">Extra request body · JSON</span>
                        <textarea :value="extraBodyText(model)" @input="setExtraBody(model, $event.target.value)" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 font-mono text-xs text-content focus:border-accent focus:outline-none" placeholder="{}" />
                        <span v-if="extraBodyErrors[model.id]" class="mt-1 block text-[11px] text-red-400">Invalid JSON object</span>
                      </label>
                    </template>

                    <p v-if="managerError" class="text-xs text-red-400">{{ managerError }}</p>
                    <button v-if="isFlexibleProvider(activeProvider)" type="button" @click="saveModelSettings(model)" :disabled="managerSaving || Boolean(extraBodyErrors[model.id])" class="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">{{ managerSaving ? 'Saving…' : 'Save model settings' }}</button>
                    </template>
                  </div>
                </div>
                <button v-if="!selectedManagerModel && canAddProviderModel" type="button" @click="startAddProviderModel" class="mt-1 flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-blue-500/[0.04]">
                  <span class="flex h-9 w-9 shrink-0 items-center justify-center text-blue-400"><svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg></span>
                  <span class="min-w-0 flex-1"><span class="block text-sm font-medium text-blue-400">Add a model</span></span>
                </button>
              </div>
            </div>
            <div v-if="!selectedManagerModel && activeManager !== 'stimma' && activeProvider && !activeProvider._unconfigured" class="mt-8 flex justify-end">
              <button type="button" @click="removeProvider(activeProvider)" class="text-xs text-red-400 hover:text-red-300">
                Disconnect
              </button>
            </div>
            </template>
          </div>
    </div>

    <!-- Existing local endpoint: preserve the proven endpoint workflow. -->
    <div v-else-if="legacyOpen" class="-m-6 min-h-full" @keydown.escape.stop="closeLegacyProvider">
          <div class="flex items-center gap-3 px-6 pb-2 pt-4">
            <button type="button" @click="closeLegacyProvider" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-content-secondary hover:bg-overlay-subtle hover:text-content">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="m15 18-6-6 6-6" /></svg>
            </button>
            <div class="min-w-0">
              <h4 class="truncate text-base font-medium text-content">{{ legacyProvider?.name || 'OpenAI-compatible endpoint' }}</h4>
              <p class="mt-0.5 truncate text-xs text-content-tertiary">{{ legacyDraft.model || 'No model selected' }}</p>
            </div>
          </div>
          <div class="space-y-6 px-6 py-4">
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="block sm:col-span-2">
                <span class="mb-1 block text-xs text-content-tertiary">Endpoint URL</span>
                <input v-model="legacyDraft.url" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">API key <span class="text-content-muted">(optional)</span></span>
                <input v-model="legacyKeyDraft" type="password" autocomplete="off" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" :placeholder="legacyDraft.api_key_set ? 'Leave blank to keep current key' : 'Leave empty if not required'" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-content-tertiary">Model</span>
                <SettingsDropdown v-if="legacyModels.length" v-model="legacyDraft.model" control :options="legacyModels.map(model => ({ value: model, label: model }))" @update:model-value="scheduleLegacyProbe" />
                <input v-else v-model="legacyDraft.model" @blur="scheduleLegacyProbe" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-accent focus:outline-none" />
              </label>
            </div>

            <div class="py-2">
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

            <div class="py-2">
              <div class="text-xs font-medium text-content">System prompt policy</div>
              <p class="mt-1 text-[11px] leading-relaxed text-content-muted">Choose whether Stimma adds its Content Policy to this model's system prompt.</p>
              <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                <input v-model="legacyDraft.content_policy_enabled" :value="true" type="radio" class="mt-0.5" />
                <span><span class="block text-xs text-content">Include Stimma's Content Policy</span><span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Adds the policy to the system prompt. With aligned models, stating it typically increases permissiveness and creative control while making refusals clearer.</span></span>
              </label>
              <label class="mt-3 flex cursor-pointer items-start gap-2.5">
                <input v-model="legacyDraft.content_policy_enabled" :value="false" type="radio" class="mt-0.5" />
                <span><span class="block text-xs text-content">Do not include it</span><span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Does not add Stimma's Content Policy to the system prompt. The model's built-in policy remains in effect.</span></span>
              </label>
              <label class="mt-3 block">
                <span class="mb-1 block text-[11px] text-content-tertiary">Additional instructions</span>
                <textarea v-model="legacyDraft.extra_system_prompt" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 text-xs text-content focus:border-accent focus:outline-none" placeholder="Appended to the system prompt for this model." />
              </label>
            </div>

            <div class="py-2">
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

            <div class="py-2">
              <div class="mb-1 flex items-baseline justify-between"><label class="text-xs font-medium text-content">Context window</label><span class="text-xs tabular-nums text-content-secondary">{{ Math.round(legacyDraft.max_context_tokens / 1024) }}k tokens</span></div>
              <input v-model.number="legacyDraft.max_context_tokens" type="range" min="32768" max="262144" step="32768" class="w-full accent-blue-500" />
              <p class="mt-1 text-[11px] text-content-muted">Match the model's configured context length. Stimma compacts history at about 80% of this.</p>
            </div>

            <label class="block py-2">
              <span class="text-xs font-medium text-content">Extra request body</span>
              <span class="mb-2 mt-0.5 block text-[11px] text-content-muted">Merged into every request for this model.</span>
              <textarea v-model="legacyExtraBodyText" rows="3" class="w-full rounded-md border border-edge bg-surface-raised px-2.5 py-2 font-mono text-xs text-content focus:border-accent focus:outline-none" placeholder='{ "repetition_penalty": 1.05 }' />
              <span v-if="legacyExtraBodyError" class="mt-1 block text-[11px] text-red-400">{{ legacyExtraBodyError }}</span>
            </label>
            <p v-if="legacyActionError" class="text-xs text-red-400">{{ legacyActionError }}</p>
          </div>
          <div class="flex items-center justify-between px-6 pb-4 pt-2">
            <button type="button" @click="removeLegacyProvider" :disabled="legacySaving" class="inline-flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 disabled:opacity-50">
              <TrashIcon /> Remove endpoint
            </button>
            <button type="button" @click="saveLegacyEndpoint" :disabled="legacySaving || Boolean(legacyExtraBodyError)" class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">{{ legacySaving ? 'Saving…' : 'Save' }}</button>
          </div>
    </div>

  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import { useAvailableModels } from '../../../composables/useAvailableModels'
import { useAuth } from '../../../composables/useAuth'
import { useCloudAccount } from '../../../composables/useCloudAccount'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'
import ModelVendorIcon from '../../models/ModelVendorIcon.vue'
import ProviderBrandIcon from '../../models/ProviderBrandIcon.vue'
import ProviderModelSetup from '../ProviderModelSetup.vue'
import { getModelVendorInfo, MODEL_VENDOR_OPTIONS, resolveModelVendorId, sortModelsByBrand } from '../../../utils/modelVendors'

const ChevronIcon = defineComponent({
  props: { open: Boolean },
  setup(props) {
    return () => h('svg', { class: ['h-4 w-4 shrink-0 text-content-muted transition-transform', props.open ? 'rotate-90' : ''], fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.5' }, [h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'm9 5 7 7-7 7' })])
  },
})
const props = defineProps({
  llmSettings: { type: Array, default: () => [] },
  setupRequired: { type: Boolean, default: false },
  // Setup-wizard variant: no section header/banner, primary providers only
  // (with a "See all" expander); connect flows are unchanged.
  wizard: { type: Boolean, default: false },
})
defineEmits(['navigate'])

const providerKinds = [
  { id: 'openai', name: 'OpenAI', description: 'Ensuring artificial general intelligence benefits all of humanity.', apiKeyHelp: 'Create or manage keys in the OpenAI Platform.', apiKeyUrl: 'https://platform.openai.com/api-keys' },
  { id: 'anthropic', name: 'Anthropic', description: 'Making AI systems you can rely on.', apiKeyHelp: 'Create or manage keys in the Claude Console.', apiKeyUrl: 'https://platform.claude.com/settings/keys' },
  { id: 'google', name: 'Google', description: 'Gemini models from Google.', apiKeyHelp: 'Create or manage keys in Google AI Studio.', apiKeyUrl: 'https://aistudio.google.com/app/apikey' },
  { id: 'xai', name: 'xAI', description: 'Accelerating human scientific discovery.', apiKeyHelp: 'Create or manage keys in the xAI Console.', apiKeyUrl: 'https://console.x.ai/' },
  { id: 'together', name: 'Together AI', description: 'Open models through Together AI.', apiKeyHelp: 'Create or manage keys in your Together AI account.', apiKeyUrl: 'https://api.together.ai/settings/api-keys' },
  { id: 'fireworks', name: 'Fireworks AI', description: 'Open models through Fireworks AI.', apiKeyHelp: 'Create or manage keys in your Fireworks AI account.', apiKeyUrl: 'https://app.fireworks.ai/settings/users/api-keys' },
  { id: 'openrouter', name: 'OpenRouter', description: 'Access hundreds of models with one key.', apiKeyHelp: 'Create or manage keys in your OpenRouter account.', apiKeyUrl: 'https://openrouter.ai/settings/keys' },
  { id: 'local', name: 'Local endpoint', description: 'Connect to LM Studio, vLLM, llama.cpp, Ollama, or another compatible server.' },
]
const modelVendorOptions = MODEL_VENDOR_OPTIONS
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

const { selectableModels, cloudStatus, cloudMessage, fetchModels, invalidateCache } = useAvailableModels()
const { signInWithBrowser, isAuthenticated } = useAuth()
const { cloudUser, fetchCloudAccount, cloudBaseUrl, ensureCloudBaseUrl } = useCloudAccount()

// Signed in but no balance: the catalog still lists models, but none of them
// will actually run — surface that instead of a reassuring model count.
const cloudNeedsCredits = computed(() => (
  cloudUser.value != null && Number(cloudUser.value.credits ?? 0) <= 0
))

const cloudConnecting = ref(false)
const cloudConnectError = ref('')

async function handleCloudConnect() {
  if (cloudConnecting.value) return
  cloudConnecting.value = true
  cloudConnectError.value = ''
  try {
    await signInWithBrowser(props.wizard ? 'create' : 'sign-in')
    await refreshAll()
  } catch (error) {
    cloudConnectError.value = error?.message || 'Could not sign in to Stimma.'
  } finally {
    cloudConnecting.value = false
  }
}
const providers = ref([])
const modelPrompts = ref({})

const cloudModels = computed(() => selectableModels.value.filter(model => model.source === 'stimma_cloud'))
const remoteProviderRows = computed(() => providerKinds
  .filter(kind => kind.id !== 'local')
  .map(kind => providers.value.find(provider => provider.kind === kind.id) || {
    id: null,
    kind: kind.id,
    name: kind.name,
    models: [],
    api_key_set: false,
    last_test_passed: null,
    last_error: null,
    _unconfigured: true,
  }))
// Wizard variant: lead with the primary providers; the rest sit behind
// "See all". Configured providers always show regardless of tier.
const WIZARD_PRIMARY_KINDS = new Set(['openai', 'anthropic', 'openrouter'])
const showAllProviders = ref(false)
const visibleRemoteProviderRows = computed(() => {
  if (!props.wizard || showAllProviders.value) return remoteProviderRows.value
  return remoteProviderRows.value.filter(provider => WIZARD_PRIMARY_KINDS.has(provider.kind) || !provider._unconfigured)
})
const hiddenRemoteProviderCount = computed(() => remoteProviderRows.value.length - visibleRemoteProviderRows.value.length)
const localProviders = computed(() => providers.value.filter(provider => provider.kind === 'local'))

const legacyOverride = ref(undefined)
const legacyEndpoint = computed(() => {
  if (legacyOverride.value !== undefined) return legacyOverride.value
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
function modelSummary(items) {
  const names = items.map(item => item.name || item.model_id).filter(Boolean)
  if (!names.length) return 'No models selected'
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} +${names.length - 3}` : names.join(', ')
}
function modelKey(model) { return model.slug || model.id }
function modelVendor(model) { return getModelVendorInfo(model)?.label || 'Custom model' }
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
  if (isAuthenticated.value) fetchCloudAccount().catch(() => {})
  await Promise.all([fetchModels(null, true), loadProviders(), loadPromptSettings()])
}
// Local model flow
const addOpen = ref(false)
const addDraft = ref({ kind: 'local', name: '', base_url: 'http://localhost:1234/v1', api_key: '' })
const addDiscoveredModels = ref([])
const addSaving = ref(false)
const addError = ref('')

function openAddLocalProvider() {
  addDraft.value = { kind: 'local', name: '', base_url: 'http://localhost:1234/v1', api_key: '' }
  addDiscoveredModels.value = []
  addError.value = ''
  addOpen.value = true
}
function closeAddProvider() { addOpen.value = false }
async function advanceAddProvider() {
  addSaving.value = true
  addError.value = ''
  try {
    const preview = await axios.post(`${getApiBase()}/models/providers/discover`, addDraft.value)
    addDiscoveredModels.value = preview.data.models || []
    const response = await axios.post(`${getApiBase()}/models/providers`, {
      ...addDraft.value,
      model_ids: [],
    })
    await refreshAll()
    closeAddProvider()
    openProvider(response.data)
    if (addDiscoveredModels.value.length) await startAddProviderModel()
  } catch (error) {
    addError.value = error.response?.data?.detail || 'Could not add this local model.'
  } finally {
    addSaving.value = false
  }
}

// Provider manager
const managerOpen = ref(false)
const managerBody = ref(null)
const activeManager = ref(null)
const activeProvider = ref(null)
const providerKeyDraft = ref('')
const editingProviderKey = ref(false)
const managerSaving = ref(false)
const managerError = ref('')
const testingId = ref(null)
const discoveredModels = ref([])
const providerModelsLoaded = ref(false)
const managerLoadingModels = ref(false)
const managerTestingModel = ref(false)
const modelAddStep = ref(null)
const modelSetupDraft = ref(null)
const modelSetupReturnToCatalog = ref(false)
const modelSearch = ref('')
const customizingModelId = ref(null)
const extraBodyDrafts = ref({})
const extraBodyErrors = ref({})

const managerTitle = computed(() => activeManager.value === 'stimma' ? 'Stimma' : activeProvider.value?.name || '')
const activeProviderKind = computed(() => providerKinds.find(item => item.id === activeProvider.value?.kind) || null)
const managerModels = computed(() => sortModelsByBrand(activeManager.value === 'stimma' ? cloudModels.value : (activeProvider.value?.models || [])))
const selectedManagerModel = computed(() => modelSetupDraft.value || managerModels.value.find(model => modelKey(model) === customizingModelId.value) || null)
const managerPageModels = computed(() => selectedManagerModel.value ? [selectedManagerModel.value] : managerModels.value)
const unselectedProviderModels = computed(() => {
  const selected = new Set((activeProvider.value?.models || []).map(model => model.model_id))
  return discoveredModels.value.filter(model => !selected.has(model.id))
})
const availableProviderModels = computed(() => {
  const query = modelSearch.value.trim().toLowerCase()
  return unselectedProviderModels.value.filter(model => !query || `${model.name} ${model.id}`.toLowerCase().includes(query))
})
const canAddProviderModel = computed(() => providerModelsLoaded.value && unselectedProviderModels.value.length > 0)
// The zero-balance row reads "Add credits" — clicking it must go to the web
// dashboard, not the model catalog (which lists models the user can't run).
async function openAddCredits() {
  await ensureCloudBaseUrl()
  const url = `${cloudBaseUrl.value}/link/addcredits`
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}
function openStimmaAccount() {
  activeManager.value = 'stimma'
  activeProvider.value = null
  customizingModelId.value = null
  modelAddStep.value = null
  modelSetupDraft.value = null
  modelSetupReturnToCatalog.value = false
  managerOpen.value = true
}
function openProvider(provider) {
  activeManager.value = provider.id || `unconfigured-${provider.kind}`
  activeProvider.value = clone(provider)
  providerKeyDraft.value = ''
  editingProviderKey.value = Boolean(provider._unconfigured)
  managerError.value = ''
  customizingModelId.value = null
  modelAddStep.value = null
  modelSetupDraft.value = null
  modelSetupReturnToCatalog.value = false
  modelSearch.value = ''
  discoveredModels.value = []
  providerModelsLoaded.value = false
  extraBodyDrafts.value = Object.fromEntries(provider.models.map(model => [model.id, JSON.stringify(model.extra_body || {}, null, 2)]))
  extraBodyErrors.value = {}
  managerOpen.value = true
  if (provider.id && isFlexibleProvider(provider) && !provider._unconfigured) {
    void loadProviderModels(activeProvider.value, { silent: true })
  }
}
function closeManager() {
  modelProfileRequestId += 1
  managerTestingModel.value = false
  customizingModelId.value = null
  modelAddStep.value = null
  modelSetupDraft.value = null
  modelSetupReturnToCatalog.value = false
  managerOpen.value = false
}
function managerBack() {
  if (selectedManagerModel.value || modelAddStep.value) closeModelSettings()
  else closeManager()
}
function handleEscape() {
  if (addOpen.value) {
    closeAddProvider()
    return true
  }
  if (managerOpen.value) {
    managerBack()
    return true
  }
  if (legacyOpen.value) {
    closeLegacyProvider()
    return true
  }
  return false
}
defineExpose({ handleEscape })
function isFlexibleProvider(provider) { return provider && ['openrouter', 'together', 'fireworks', 'local'].includes(provider.kind) }
function isRemoteProvider(provider) { return provider && provider.kind !== 'local' }
function beginProviderKeyEdit() {
  providerKeyDraft.value = ''
  managerError.value = ''
  editingProviderKey.value = true
}
function cancelProviderKeyEdit() {
  providerKeyDraft.value = ''
  managerError.value = ''
  editingProviderKey.value = false
}
async function openProviderKeyPage() {
  const url = activeProviderKind.value?.apiKeyUrl
  if (!url) return
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}
function resetManagerScroll() { nextTick(() => managerBody.value?.scrollTo({ top: 0 })) }
function openModelSettings(model) { modelAddStep.value = null; modelSetupDraft.value = null; modelSetupReturnToCatalog.value = false; customizingModelId.value = modelKey(model); resetManagerScroll() }
function closeModelSettings(toProvider = false) {
  modelProfileRequestId += 1
  managerTestingModel.value = false
  customizingModelId.value = null
  modelSetupDraft.value = null
  managerError.value = ''
  if (!toProvider && modelAddStep.value === 'setup' && modelSetupReturnToCatalog.value) {
    modelAddStep.value = 'choose'
  } else {
    modelAddStep.value = null
    modelSearch.value = ''
  }
  modelSetupReturnToCatalog.value = false
  resetManagerScroll()
}
function modelPrompt(model) {
  if (activeManager.value === 'stimma') {
    if (!modelPrompts.value[model.slug]) modelPrompts.value[model.slug] = { content_policy_enabled: true, extra_system_prompt: '' }
    return modelPrompts.value[model.slug]
  }
  if (model.content_policy_enabled == null) model.content_policy_enabled = true
  if (model.extra_system_prompt == null) model.extra_system_prompt = ''
  return model
}
function updateModelPolicy(model, enabled) {
  modelPrompt(model).content_policy_enabled = enabled
  if (!isFlexibleProvider(activeProvider.value)) saveModelSettings(model)
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
  if (isRemoteProvider(activeProvider.value) && !providerKeyDraft.value) return
  managerSaving.value = true
  managerError.value = ''
  try {
    if (activeProvider.value._unconfigured) {
      const response = await axios.post(`${getApiBase()}/models/providers`, {
        kind: activeProvider.value.kind,
        api_key: providerKeyDraft.value,
        model_ids: [],
      })
      activeManager.value = response.data.id
      activeProvider.value = clone(response.data)
      providerKeyDraft.value = ''
      editingProviderKey.value = false
      await refreshAll()
      if (isFlexibleProvider(activeProvider.value)) {
        if (activeProvider.value.models.length === 1) openModelSettings(activeProvider.value.models[0])
        else await startAddProviderModel()
      }
      return
    }
    const payload = isRemoteProvider(activeProvider.value)
      ? { api_key: providerKeyDraft.value }
      : { name: activeProvider.value.name, base_url: activeProvider.value.base_url }
    if (!isRemoteProvider(activeProvider.value) && providerKeyDraft.value) payload.api_key = providerKeyDraft.value
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, payload)
    activeProvider.value = clone(response.data)
    providerKeyDraft.value = ''
    editingProviderKey.value = false
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
async function loadProviderModels(provider, { silent = false } = {}) {
  const providerId = provider?.id
  if (!providerId) return
  if (!silent) {
    managerError.value = ''
    managerLoadingModels.value = true
  }
  try {
    const response = await axios.get(`${getApiBase()}/models/providers/${providerId}/models`)
    if (activeProvider.value?.id !== providerId) return
    discoveredModels.value = response.data.models || []
    providerModelsLoaded.value = true
  } catch (error) {
    if (!silent) managerError.value = error.response?.data?.detail || 'Could not load models.'
  } finally {
    if (!silent) managerLoadingModels.value = false
  }
}

async function startAddProviderModel() {
  modelAddStep.value = 'choose'
  modelSetupDraft.value = null
  modelSetupReturnToCatalog.value = false
  customizingModelId.value = null
  modelSearch.value = ''
  resetManagerScroll()
  await loadProviderModels(activeProvider.value)
  if (availableProviderModels.value.length === 1) {
    chooseProviderModel(availableProviderModels.value[0], false)
  }
}

function providerModelDraft(discovered) {
  return {
    id: `${activeProvider.value.id}:${discovered.id}`,
    model_id: discovered.id,
    name: discovered.name || discovered.id,
    model_vendor: resolveModelVendorId(discovered) || null,
    enabled: true,
    max_context_tokens: discovered.context_length || 128000,
    input_modalities: ['text'],
    supports_tools: false,
    reasoning: { mode: 'none', levels: ['off'], default: 'off', quick_task: 'off', control: 'none', wire_levels: { off: 'off' } },
    content_policy_enabled: true,
    extra_body: {},
    extra_system_prompt: '',
    reasoning_control_source: 'auto',
    last_test_results: {},
  }
}

async function profileProviderModelCandidate(discovered) {
  const draft = providerModelDraft(discovered)
  const response = await axios.post(`${getApiBase()}/models/providers/${activeProvider.value.id}/models/profile`, {
    model_id: draft.model_id,
    name: draft.name,
    max_context_tokens: draft.max_context_tokens,
  })
  return response.data.model
}

function chooseProviderModel(discovered, returnToCatalog = true) {
  modelSetupDraft.value = providerModelDraft(discovered)
  modelSetupReturnToCatalog.value = returnToCatalog
  modelAddStep.value = 'setup'
  customizingModelId.value = null
  managerError.value = ''
  resetManagerScroll()
  void profileManagerModel(modelSetupDraft.value)
}

let modelProfileRequestId = 0
async function profileManagerModel(model) {
  const requestId = ++modelProfileRequestId
  managerTestingModel.value = true
  managerError.value = ''
  try {
    const profiled = await profileProviderModelCandidate({
      id: model.model_id,
      name: model.name,
      context_length: model.max_context_tokens,
    })
    if (requestId !== modelProfileRequestId) return
    if (modelSetupDraft.value) modelSetupDraft.value = profiled
    else {
      const index = activeProvider.value.models.findIndex(item => item.id === model.id)
      if (index !== -1) activeProvider.value.models.splice(index, 1, profiled)
      await saveModelSettings(profiled)
    }
  } catch (error) {
    if (requestId === modelProfileRequestId) managerError.value = error.response?.data?.detail || 'The model test failed.'
  } finally {
    if (requestId === modelProfileRequestId) managerTestingModel.value = false
  }
}

async function commitProviderModel() {
  if (!modelSetupDraft.value?.last_test_passed) return
  managerSaving.value = true
  managerError.value = ''
  try {
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, {
      models: [...activeProvider.value.models, modelSetupDraft.value],
    })
    activeProvider.value = clone(response.data)
    await refreshAll()
    closeModelSettings(true)
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not add this model.'
  } finally {
    managerSaving.value = false
  }
}

async function removeProviderModel(model) {
  managerSaving.value = true
  managerError.value = ''
  try {
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, {
      models: activeProvider.value.models.filter(item => item.id !== model.id),
    })
    activeProvider.value = clone(response.data)
    await refreshAll()
    closeModelSettings()
  } catch (error) {
    managerError.value = error.response?.data?.detail || 'Could not remove this model.'
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
const legacyActionError = ref('')
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
  legacyActionError.value = ''
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
async function removeLegacyProvider() {
  legacySaving.value = true
  legacyActionError.value = ''
  try {
    const payload = {
      source: 'auto',
      endpoint_url: '',
      endpoint_model: '',
      endpoint_api_key: '',
      endpoint_extra_system_prompt: '',
      endpoint_extra_body: {},
      endpoint_reasoning_method: '',
      endpoint_reasoning_method_source: 'auto',
    }
    await Promise.all([
      axios.patch(`${getApiBase()}/settings/llms/agent`, payload),
      axios.patch(`${getApiBase()}/settings/llms/agent-fast`, payload),
    ])
    legacyOverride.value = null
    closeLegacyProvider()
    invalidateCache()
    await fetchModels(null, true)
  } catch (error) {
    legacyActionError.value = error.response?.data?.detail || 'Could not remove this endpoint.'
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

onMounted(refreshAll)
</script>
