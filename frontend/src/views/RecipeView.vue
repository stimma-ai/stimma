<template>
  <div class="flex flex-col h-full bg-base relative">
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :media-list="slideshowState.mediaList"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      :approval-context="slideshowApprovalContext"
      @close="exitSlideshow"
      @update:current-media-id="updateCurrentMediaId"
      @approve="onSlideshowApprove"
      @reject="onSlideshowReject"
      @unapprove="onSlideshowUnapprove"
    />

    <div
      v-if="showCodeIntroModal"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 px-4"
      @click.self="dismissCodeIntro"
    >
      <div class="w-full max-w-md rounded-lg border border-edge bg-surface shadow-2xl">
        <div class="px-5 py-4 border-b border-edge-subtle flex items-center gap-3">
          <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-blue-500/15 border border-blue-500/50">
            <BoltIcon class="h-5 w-5 text-blue-500" />
          </div>
          <div class="min-w-0">
            <h2 class="text-sm font-semibold text-content">You can skip the code</h2>
            <p class="mt-0.5 text-xs text-content-muted">Most recipe work happens in Steps and Workflow.</p>
          </div>
        </div>
        <div class="px-5 py-4 text-sm leading-relaxed text-content-secondary space-y-3">
          <p>
            Use the Steps and Workflow tabs to build, run, and adjust your recipe. That is the friendly way to work with recipes.
          </p>
          <p>
            The Code tab is just here in case you ever want to peek behind the scenes or make an advanced edit. You do not need to read it or understand it to use Stimma.
          </p>
        </div>
        <div class="px-5 py-3 border-t border-edge-subtle flex justify-end">
          <button
            type="button"
            class="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
            @click="dismissCodeIntro"
          >
            Got it
          </button>
        </div>
      </div>
    </div>

    <!-- Control strip -->
    <div class="relative flex items-center px-4 py-2 border-b border-edge-subtle flex-shrink-0 gap-3">
      <!-- Left: name + meta -->
      <div class="flex items-center gap-3 min-w-0 flex-shrink">
        <template v-if="editingName">
          <input
            ref="nameInputEl"
            v-model="editingNameValue"
            class="bg-base border border-edge rounded px-2 py-1 text-sm font-medium text-content focus:outline-none focus:border-blue-500/70 min-w-0 max-w-xs"
            @blur="saveName"
            @keydown.enter.prevent="saveName"
            @keydown.esc.prevent="cancelEditName"
          />
        </template>
        <template v-else>
          <button
            v-if="recipe?.name"
            class="text-sm font-semibold text-content hover:text-blue-400 transition-colors truncate max-w-[200px]"
            @click="startEditName"
            :title="recipe.name"
          >
            {{ recipe.name }}
          </button>
          <button
            v-else
            class="text-sm font-semibold italic text-content-muted hover:text-content-secondary transition-colors truncate max-w-[200px]"
            @click="startEditName"
          >
            Name this recipe...
          </button>
        </template>

        <span v-if="parentName" class="text-[11px] text-content-muted flex-shrink-0">
          Copy of
          <button class="text-blue-400 hover:underline" @click="openParent">{{ parentName }}</button>
        </span>

        <div v-if="copies.length > 0" class="relative flex-shrink-0" ref="copiesRootEl">
          <button
            class="text-[11px] text-content-muted hover:text-content flex items-center gap-1 transition-colors"
            @click="toggleCopies"
            :title="copies.length === 1 ? '1 copy of this recipe' : `${copies.length} copies of this recipe`"
          >
            <span>{{ copies.length }} {{ copies.length === 1 ? 'copy' : 'copies' }}</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-3 h-3 opacity-70">
              <path fill-rule="evenodd" d="M12.53 16.28a.75.75 0 0 1-1.06 0l-7.5-7.5a.75.75 0 0 1 1.06-1.06L12 14.69l6.97-6.97a.75.75 0 1 1 1.06 1.06l-7.5 7.5Z" clip-rule="evenodd" />
            </svg>
          </button>

          <div
            v-if="copiesOpen"
            class="absolute left-0 mt-1 w-72 bg-surface border border-edge rounded-lg shadow-xl z-50 py-1 max-h-80 overflow-y-auto"
          >
            <button
              v-for="c in copies"
              :key="c.id"
              @click="openCopy(c)"
              class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
            >
              <span class="truncate flex-1">{{ c.name || `Recipe #${c.id}` }}</span>
              <span
                class="px-1.5 py-0.5 text-[10px] rounded uppercase tracking-wider flex-shrink-0"
                :class="copyStateBadge(c.execution_state)"
              >{{ c.execution_state }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Center: status + execution controls -->
      <div class="flex flex-1 min-w-0 items-center justify-center gap-2 text-xs">
        <RecipeStatusPill
          :recipe-id="recipeId"
          show-pending
          text-class="text-xs text-content-secondary"
          class="flex-shrink-0"
        />
        <button
          v-if="showStartButton"
          class="w-9 h-9 flex items-center justify-center rounded-md bg-overlay-subtle border border-edge text-content hover:bg-overlay-hover transition-colors"
          title="Start"
          @click="doPlay"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M4.5 5.653c0-1.427 1.529-2.33 2.779-1.643l11.54 6.347c1.295.712 1.295 2.573 0 3.286L7.28 19.99c-1.25.687-2.779-.217-2.779-1.643V5.653Z" clip-rule="evenodd" />
          </svg>
        </button>
        <button
          v-if="showPauseButton"
          class="w-9 h-9 flex items-center justify-center rounded-md bg-overlay-subtle border border-edge text-content hover:bg-overlay-hover transition-colors"
          title="Pause"
          @click="doPause"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M6.75 5.25a.75.75 0 0 1 .75-.75H9a.75.75 0 0 1 .75.75v13.5a.75.75 0 0 1-.75.75H7.5a.75.75 0 0 1-.75-.75V5.25Zm7.5 0A.75.75 0 0 1 15 4.5h1.5a.75.75 0 0 1 .75.75v13.5a.75.75 0 0 1-.75.75H15a.75.75 0 0 1-.75-.75V5.25Z" clip-rule="evenodd" />
          </svg>
        </button>
        <button
          v-if="showResumeButton"
          class="w-9 h-9 flex items-center justify-center rounded-md bg-blue-500/20 border border-blue-500/40 text-blue-400 hover:bg-blue-500/30 transition-colors"
          title="Resume"
          @click="doPlay"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M4.5 5.653c0-1.427 1.529-2.33 2.779-1.643l11.54 6.347c1.295.712 1.295 2.573 0 3.286L7.28 19.99c-1.25.687-2.779-.217-2.779-1.643V5.653Z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>

      <!-- Right: chat toggle + more menu -->
      <div class="flex items-center gap-1.5 flex-shrink-0 justify-end">
        <!-- Chat menu: new session, switch session, show/hide panel -->
        <div class="relative" ref="chatMenuContainerRef">
          <button
            class="flex items-center gap-1.5 px-2.5 h-8 rounded-md text-xs font-medium border transition-colors"
            :class="chatPanelOpen
              ? 'bg-blue-500/20 text-blue-400 border-blue-500/50 hover:bg-blue-500/30'
              : 'bg-overlay-subtle text-content border-edge hover:bg-overlay-hover'"
            title="Chat options"
            @click="toggleChatMenu"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
            </svg>
            Chat
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-3 h-3 opacity-70">
              <path fill-rule="evenodd" d="M12.53 16.28a.75.75 0 0 1-1.06 0l-7.5-7.5a.75.75 0 0 1 1.06-1.06L12 14.69l6.97-6.97a.75.75 0 1 1 1.06 1.06l-7.5 7.5Z" clip-rule="evenodd" />
            </svg>
          </button>

          <div
            v-if="showChatMenu"
            class="absolute right-0 mt-1 w-72 bg-surface border border-edge rounded-lg shadow-xl z-50 py-1"
          >
            <button
              @click="handleNewChatSession"
              :disabled="creatingChatSession"
              class="w-full px-3 py-1.5 text-left text-xs text-blue-400 hover:bg-blue-500/10 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              {{ creatingChatSession ? 'Starting new session…' : 'New chat session' }}
            </button>

            <div class="border-t border-edge my-1"></div>

            <div class="px-3 pt-1 pb-1 text-[10px] uppercase tracking-wider text-content-muted font-semibold">
              Switch to session
            </div>
            <div v-if="loadingChatSessions" class="px-3 py-2 text-xs text-content-muted italic">
              Loading…
            </div>
            <div v-else-if="chatSessionsError" class="px-3 py-2 text-xs text-red-400">
              Couldn't load sessions.
            </div>
            <div v-else-if="recipeChatSessions.length === 0" class="px-3 py-2 text-xs text-content-muted italic">
              No past sessions.
            </div>
            <div v-else class="max-h-64 overflow-y-auto">
              <button
                v-for="session in recipeChatSessions"
                :key="session.id"
                @click="handleSwitchChatSession(session.id)"
                class="w-full px-3 py-1.5 text-left text-xs transition-colors flex items-center gap-2"
                :class="session.id === recipeChatId
                  ? 'bg-blue-500/10 text-blue-400'
                  : 'text-content-secondary hover:bg-surface-raised'"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5 flex-shrink-0 opacity-70">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                </svg>
                <span class="truncate flex-1">{{ sessionDisplayName(session) }}</span>
                <span class="text-[10px] text-content-muted flex-shrink-0 ml-1">{{ formatSessionTime(session.updated_at) }}</span>
              </button>
            </div>

            <div class="border-t border-edge my-1"></div>

            <button
              @click="handleToggleChatPanel"
              class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
            >
              <svg v-if="chatPanelOpen" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
              </svg>
              {{ chatPanelOpen ? 'Hide chat panel' : 'Show chat panel' }}
            </button>
          </div>
        </div>

        <!-- 3-dot Menu -->
        <div class="relative" ref="menuContainerRef">
          <button
            @click="toggleMenu"
            class="w-8 h-8 flex items-center justify-center rounded-md text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
            title="More options"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
            </svg>
          </button>

          <!-- Dropdown menu -->
          <div
            v-if="showMenu"
            class="absolute right-0 mt-1 w-44 bg-surface border border-edge rounded-lg shadow-xl z-50 py-1"
          >
            <button
              @click="doCopy"
              :disabled="copying"
              class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
              </svg>
              {{ copying ? 'Making a copy…' : 'Make a copy' }}
            </button>
            <div class="border-t border-edge my-1"></div>
            <button
              @click="handleRename"
              class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
              </svg>
              Rename recipe
            </button>
            <div class="border-t border-edge my-1"></div>
            <button
              @click="handleDelete"
              class="w-full px-3 py-1.5 text-left text-xs text-red-500 hover:bg-red-500/10 transition-colors flex items-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
              Delete recipe
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Main row: (main column + resize handle) wrapper + chat sidebar -->
    <div class="flex flex-1 min-h-0">
      <!-- Left wrapper: tab subheader spans main column AND resize handle so its border butts against the chat panel's left divider -->
      <div class="flex-1 flex flex-col min-w-0">
        <!-- View tabs subheader -->
        <div class="flex items-center px-4 border-b border-edge-subtle flex-shrink-0">
          <button
            class="text-[12px] px-3 py-2 -mb-px border-b-2 transition-colors"
            :class="viewMode === 'compact'
              ? 'text-blue-400 font-medium border-blue-400'
              : 'text-content-muted hover:text-content border-transparent'"
            @click="setViewMode('compact')"
          >Steps</button>
          <button
            class="text-[12px] px-3 py-2 -mb-px border-b-2 transition-colors"
            :class="viewMode === 'graph'
              ? 'text-indigo-400 font-medium border-indigo-400'
              : 'text-content-muted hover:text-content border-transparent'"
            @click="setViewMode('graph')"
          >Workflow</button>
          <button
            class="text-[12px] px-3 py-2 -mb-px border-b-2 transition-colors"
            :class="viewMode === 'code'
              ? 'text-content font-medium border-content'
              : 'text-content-muted hover:text-content border-transparent'"
            @click="setViewMode('code')"
          >Code</button>

          <div class="ml-auto flex items-center gap-2 py-1">
            <!-- Graph view toggle: collapse foreaches into super-nodes vs show
                 every iteration's equations expanded (the raw dagre layout). -->
            <div v-if="viewMode === 'graph' && !programAttentionError" class="flex items-center gap-1">
              <div class="flex items-center rounded border border-edge-subtle overflow-hidden text-[11px]">
                <button
                  type="button"
                  class="px-2 py-0.5 transition-colors"
                  :class="graphCollapseForeach
                    ? 'bg-indigo-500 text-white'
                    : 'text-content-muted hover:text-content hover:bg-overlay-subtle'"
                  title="Collapse foreach iterations into a single super-node"
                  @click="graphCollapseForeach = true"
                >Collapsed</button>
                <button
                  type="button"
                  class="px-2 py-0.5 transition-colors border-l border-edge-subtle"
                  :class="!graphCollapseForeach
                    ? 'bg-indigo-500 text-white'
                    : 'text-content-muted hover:text-content hover:bg-overlay-subtle'"
                  title="Show every iteration's equations as raw graph nodes"
                  @click="graphCollapseForeach = false"
                >Expanded</button>
              </div>
            </div>

            <div class="relative" ref="tabMenuContainerRef">
              <button
                @click="toggleTabMenu"
                class="w-8 h-8 flex items-center justify-center rounded-md text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
                title="More options"
                aria-label="More options"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
                </svg>
              </button>

              <div
                v-if="showTabMenu"
                class="absolute right-0 mt-1 w-48 bg-surface border border-edge rounded-lg shadow-xl z-50 py-1"
              >
                <button
                  v-if="hasInputFields"
                  @click="resetInputsToDefaults"
                  class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992V4.356m-1.636 14.288A9 9 0 1 1 21 12.75v-3" />
                  </svg>
                  Reset Inputs
                </button>
                <div v-if="hasInputFields" class="border-t border-edge my-1"></div>
                <button
                  v-if="isDev"
                  @click="handleShowCodeIntroModal"
                  class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2"
                >
                  <BoltIcon class="w-3.5 h-3.5 text-blue-500" />
                  Show code intro
                </button>
                <div v-if="isDev" class="border-t border-edge my-1"></div>
                <button
                  @click="handleReparseRecipe"
                  :disabled="reparsingRecipe"
                  class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992V4.356m-1.636 14.288A9 9 0 1 1 21 12.75v-3" />
                  </svg>
                  {{ reparsingRecipe ? 'Re-processing…' : 'Re-process recipe' }}
                </button>
                <button
                  @click="handleClearRecipe"
                  :disabled="clearingRecipe"
                  class="w-full px-3 py-1.5 text-left text-xs text-red-500 hover:bg-red-500/10 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                  </svg>
                  {{ clearingRecipe ? 'Clearing…' : 'Clear recipe' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <RecipeAttentionBanner
          v-if="showRecipeAttentionBanner"
          class="mx-4 mt-4 flex-shrink-0"
          :error="attentionError"
          :error-source="attentionErrorSource"
          :blocked="allBlocked && !programAttentionError"
          :agent-busy="agentBusy"
          :fixing="fixingWithAgent"
          :dev-mode="isDev"
          :can-pause="recipe?.execution_state === 'running'"
          @fix="handleAttentionFix"
          @unblock="askAgentForHelpUnblocking"
          @pause="doPause"
        />

        <!-- Inner row: main column | resize handle -->
        <div class="flex flex-1 min-h-0">
          <!-- Main column -->
          <div class="flex-1 flex flex-col min-w-0">

            <!-- Steps mode: single scroll region with Inputs, Steps, Outputs cards -->
            <div v-if="viewMode === 'compact'" class="flex-1 overflow-y-auto px-4 py-4 custom-scrollbar">
              <div class="space-y-4">
                <div class="relative">
                  <div
                    class="space-y-4"
                    :class="programAttentionError ? 'opacity-40 grayscale pointer-events-none' : ''"
                  >
                <!-- Inputs section -->
                <section v-if="hasInputFields">
                  <div class="flex items-center gap-2 py-1.5 min-h-[40px]">
                    <span class="text-[15px] font-semibold text-content tracking-wide">Inputs</span>
                    <div class="ml-auto flex items-center gap-1.5">
                      <template v-if="hasInputFields && inputsDirty">
                        <button
                          type="button"
                          class="text-[11px] px-2 py-1 rounded border border-edge-subtle text-content-secondary hover:bg-overlay-subtle disabled:opacity-40"
                          :disabled="submittingInputs"
                          @click="inputFormRef?.discardChanges()"
                          title="Discard unsaved input changes"
                        >Revert</button>
                        <button
                          type="button"
                          class="text-[11px] px-2 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
                          :disabled="!inputsValid || submittingInputs"
                          @click="inputFormRef?.applyChanges()"
                          title="Apply the changed inputs to this recipe"
                        >{{ submittingInputs ? 'Applying…' : 'Apply inputs' }}</button>
                      </template>
                    </div>
                  </div>
                  <div class="py-3">
                    <RecipeInputForm
                      ref="inputFormRef"
                      :schema="recipe?.input_schema || null"
                      :initial-values="recipe?.inputs || null"
                      :applying="submittingInputs"
                      @submit="onInputSubmit"
                      @update:dirty="inputsDirty = $event"
                      @update:valid="inputsValid = $event"
                    />
                  </div>
                </section>

                <div
                  v-if="showRecipeEmptyState"
                  class="min-h-[360px] flex items-center justify-center px-6 py-12"
                >
                  <div class="max-w-md text-center">
                    <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-400">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M13 3 4 14h7l-1 7 9-11h-7l1-7Z" />
                      </svg>
                    </div>
                    <div class="text-[15px] font-semibold text-content">No recipe yet</div>
                    <div class="mt-2 text-[13px] leading-relaxed text-content-muted">
                      Describe the workflow in chat. The assistant will turn it into inputs, steps, and outputs here.
                    </div>
                    <button
                      v-if="!chatPanelOpen"
                      type="button"
                      class="mt-4 rounded-md bg-blue-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-blue-600"
                      @click="chatPanelOpen = true"
                    >
                      Open chat
                    </button>
                  </div>
                </div>

                <template v-else>
                    <!-- Steps section -->
                    <section>
                      <div class="flex items-center gap-2 py-2.5">
                        <span class="text-[15px] font-semibold text-content tracking-wide">Steps</span>
                        <span
                          v-if="stepsSummary"
                          class="text-[11px] text-content-muted"
                        >{{ stepsSummary }}</span>
                      </div>
                      <div class="py-3">
                        <ConnectionError v-if="state.loadError.value" @retry="state.loadAll" />
                        <div v-else-if="state.loading.value && !state.phaseTree.value" class="text-content-muted text-sm py-8 text-center">
                          Loading recipe…
                        </div>
                        <template v-else>
                          <PhaseTree
                            :root="state.phaseTree.value?.root || null"
                            :equations-by-key="state.equationsByKey.value"
                            :tasks="state.tasks.value"
                            :load-error="programAttentionError"
                            :focused-task-id="focusedTaskId"
                            :execution-state="recipe?.execution_state || 'idle'"
                            :dev-mode="isDev"
                            @invalidate-phase="doInvalidatePhase"
                            @invalidate-equation="doInvalidateEquation"
                            @reselect-equation="doReselectEquation"
                            @resolve-task="onResolveTask"
                            @resolve-error-task="onResolveErrorTask"
                            @focus-task="(t) => focusedTaskId = t.task_id"
                            @edit-recipe="openChatForEdit"
                            @fix-step-with-agent="askAgentToFixStep"
                            @register-task-ref="registerTaskRef"
                          />
                        </template>
                      </div>
                    </section>

                    <!-- Outputs section (DeliveryPanel self-hides when no items) -->
                    <DeliveryPanel
                      :equations-by-key="state.equationsByKey.value"
                      @invalidate-equation="doInvalidateEquation"
                      @fix-step-with-agent="askAgentToFixStep"
                    />
                </template>
                  </div>
                  <div
                    v-if="programAttentionError"
                    class="absolute inset-0 rounded-lg bg-base/35"
                    aria-hidden="true"
                  />
                </div>
              </div>
            </div>

            <!-- Graph view (full area, inputs/outputs live inside the graph) -->
            <div v-else-if="viewMode === 'graph'" class="flex-1 min-h-0 relative flex flex-col">
              <div class="relative flex-1 min-h-0">
                <div
                  v-if="showRecipeEmptyState && !programAttentionError"
                  class="flex h-full items-center justify-center px-6 py-12"
                >
                  <div class="max-w-md text-center">
                    <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-400">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M13 3 4 14h7l-1 7 9-11h-7l1-7Z" />
                      </svg>
                    </div>
                    <div class="text-[15px] font-semibold text-content">No recipe yet</div>
                    <div class="mt-2 text-[13px] leading-relaxed text-content-muted">
                      Describe the workflow in chat. The assistant will turn it into inputs, steps, and outputs here.
                    </div>
                    <button
                      v-if="!chatPanelOpen"
                      type="button"
                      class="mt-4 rounded-md bg-blue-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-blue-600"
                      @click="chatPanelOpen = true"
                    >
                      Open chat
                    </button>
                  </div>
                </div>
                <EquationGraph
                  v-else
                  :class="programAttentionError ? 'opacity-40 grayscale pointer-events-none' : ''"
                  :equations-by-key="state.equationsByKey.value"
                  :tasks="state.tasks.value"
                  :execution-state="recipe?.execution_state || 'idle'"
                  :dev-mode="isDev"
                  :collapse-foreach="graphCollapseForeach"
                  :recipe-id="recipeId"
                  :input-schema="recipe?.input_schema || null"
                  :input-values="recipe?.inputs || null"
                  :submitting-inputs="submittingInputs"
                  @invalidate-equation="doInvalidateEquation"
                  @fix-step-with-agent="askAgentToFixStep"
                  @resolve-task="onResolveTask"
                  @resolve-error-task="onResolveErrorTask"
                  @edit-recipe="openChatForEdit"
                  @update-inputs="onPanelInputUpdate"
                />
                <div
                  v-if="programAttentionError"
                  class="absolute inset-0 bg-base/35"
                  aria-hidden="true"
                />
              </div>
            </div>

            <!-- Code view (full area) -->
            <div v-else-if="viewMode === 'code'" class="flex-1 min-h-0 relative flex flex-col">
              <div
                v-if="codeDirty || savingCode"
                class="flex items-center gap-2 px-4 py-1.5 border-y border-edge-subtle bg-blue-500/5 min-h-[40px]"
                :class="showRecipeAttentionBanner ? '' : 'border-t-0'"
              >
                <span class="text-[12px] text-content-secondary">
                  Unsaved changes in <code class="font-mono text-[11px] text-content">program.py</code>
                </span>
                <span v-if="savingCode" class="text-[11px] text-content-muted">Re-processing recipe…</span>
                <div class="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    class="text-[11px] px-2 py-1 rounded border border-edge-subtle text-content-secondary hover:bg-overlay-subtle disabled:opacity-40"
                    :disabled="savingCode"
                    @click="revertCodeEdit"
                    title="Discard unsaved code changes"
                  >Revert</button>
                  <button
                    type="button"
                    class="text-[11px] px-2 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
                    :disabled="!codeDirty || savingCode"
                    @click="saveCodeEdit"
                    title="Save program.py and re-process the recipe"
                  >{{ savingCode ? 'Saving…' : 'Save' }}</button>
                </div>
              </div>
              <RecipeCodeView
                ref="codeViewRef"
                :code="programCodeDraft"
                :baseline-code="programCode"
                :loading="programCodeLoading"
                :editing="true"
                :error-lines="codeErrorLines"
                @update:code="handleCodeDraftUpdate"
                @update:dirty="codeDirty = $event"
                @save-request="saveCodeEdit"
                class="flex-1 min-h-0"
              >
                <template #below-editor>
                  <RecipeCodeErrorsPanel
                    :errors="codeErrors"
                    :selected-id="selectedCodeErrorId"
                    @select="onSelectCodeError"
                  />
                </template>
              </RecipeCodeView>
            </div>
          </div>

          <!-- Resize handle (inside left wrapper so the tab subheader's border extends across it) -->
          <div
            v-if="chatPanelOpen"
            class="w-1 flex-shrink-0 cursor-col-resize select-none hover:bg-blue-500/40 active:bg-blue-500/60 transition-colors"
            @mousedown="startChatResize"
          />
        </div>
      </div>

      <!-- Chat sidebar (open by default) -->
      <div v-if="chatPanelOpen" class="flex-shrink-0 border-l border-edge-subtle flex flex-col bg-surface" :style="{ width: chatPanelWidth + 'px' }">

        <div class="flex-1 min-h-0 flex flex-col">
          <div v-if="chatLoading" class="flex-1 flex items-center justify-center text-[12px] text-content-muted">
            Connecting…
          </div>
          <div v-else-if="chatError" class="flex-1 flex items-center justify-center px-4 text-center">
            <div class="space-y-2">
              <div class="text-[13px] text-red-400">Couldn't open chat.</div>
              <button
                class="text-[12px] px-2 py-1 rounded bg-overlay-subtle border border-edge text-content hover:bg-overlay-hover"
                @click="ensureRecipeChat"
              >Retry</button>
            </div>
          </div>
          <ChatView
            v-else-if="recipeChatId != null"
            :key="recipeChatId"
            :chat-id="recipeChatId"
            :embedded="true"
            class="flex-1 min-h-0"
          >
            <template #context-header>
              <RecipeContextTray />
            </template>
          </ChatView>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted, provide, type WatchStopHandle } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import ConnectionError from '../components/ConnectionError.vue'
import PhaseTree from '../components/recipe/PhaseTree.vue'
import DeliveryPanel from '../components/recipe/DeliveryPanel.vue'
import EquationGraph from '../components/recipe/EquationGraph.vue'
import RecipeAttentionBanner from '../components/recipe/RecipeAttentionBanner.vue'
import RecipeCodeView from '../components/recipe/RecipeCodeView.vue'
import RecipeCodeErrorsPanel from '../components/recipe/RecipeCodeErrorsPanel.vue'
import RecipeInputForm from '../components/recipe/RecipeInputForm.vue'
import RecipeStatusPill from '../components/recipe/RecipeStatusPill.vue'
import ChatView from './ChatView.vue'
import RecipeContextTray from '../components/recipe/RecipeContextTray.vue'
import { RECIPE_CHAT_ID_KEY } from '../composables/useRecipeReferences'
import SlideshowMode from '../components/SlideshowMode.vue'
import { useRecipeState } from '../composables/useRecipeState'
import { useRecipeCodeErrors } from '../composables/useRecipeCodeErrors'
import { useRecipesApi, type Recipe, type RecipeTask, type RecipeEquation, type PhaseNode as PhaseNodeType } from '../composables/useRecipesApi'
import { useWebSocket } from '../composables/useWebSocket'
import { useSlideshow } from '../composables/useSlideshow'
import { useMediaApi } from '../composables/useMediaApi'
import { useToasts } from '../composables/useToasts'
import { devModeRef } from '../appConfig'
import { recipeMediaSlideshowKey } from '../components/recipe/recipeMediaSlideshow'
import { equationDurationMs, formatEquationDurationMs } from '../utils/equationDuration'
import { makeStorageKey } from '../utils/storageKeys'
import { parseRecipeError } from '../utils/recipeErrors'
import { BoltIcon } from '@heroicons/vue/24/solid'

const props = defineProps<{ id?: string | number }>()
const route = useRoute()
const router = useRouter()
const api = useRecipesApi()
const { getMediaItem } = useMediaApi()
const { addToast } = useToasts()
const { slideshowState, enterSlideshow, exitSlideshow: exitBaseSlideshow, updateCurrentMediaId } = useSlideshow()

const recipeId = computed(() => {
  const p = props.id ?? route.params.id
  if (p == null) return null
  return String(p)
})

const state = useRecipeState(recipeId)
const recipe = state.recipe

function isVisibleRecipeEquation(eq: RecipeEquation): boolean {
  if (eq.is_scaffolding && eq.status !== 'failed') return false
  if (eq.equation_type === 'code' && eq.status !== 'failed') return false
  return true
}

function getOrderedPhaseEquations(phasePath: string[]): RecipeEquation[] {
  const pathKey = JSON.stringify(phasePath || [])
  const allInPhase = Array.from(state.equationsByKey.value.values()).filter((eq) =>
    JSON.stringify(eq.phase_path || []) === pathKey
  )
  const keys = new Set(allInPhase.map((eq) => eq.equation_key))
  const indexOf = new Map<string, number>()
  allInPhase.forEach((eq, index) => indexOf.set(eq.equation_key, index))

  const inDegree = new Map<string, number>()
  const outEdges = new Map<string, string[]>()
  for (const eq of allInPhase) {
    inDegree.set(eq.equation_key, 0)
    outEdges.set(eq.equation_key, [])
  }
  for (const eq of allInPhase) {
    for (const dep of eq.dependencies || []) {
      if (!keys.has(dep)) continue
      outEdges.get(dep)?.push(eq.equation_key)
      inDegree.set(eq.equation_key, (inDegree.get(eq.equation_key) || 0) + 1)
    }
  }

  const ready: string[] = []
  for (const eq of allInPhase) {
    if ((inDegree.get(eq.equation_key) || 0) === 0) ready.push(eq.equation_key)
  }
  ready.sort((a, b) => (indexOf.get(a) || 0) - (indexOf.get(b) || 0))

  const byKey = new Map(allInPhase.map((eq) => [eq.equation_key, eq]))
  const ordered: RecipeEquation[] = []
  while (ready.length > 0) {
    const key = ready.shift()!
    const eq = byKey.get(key)
    if (eq) ordered.push(eq)
    for (const next of outEdges.get(key) || []) {
      const degree = (inDegree.get(next) || 0) - 1
      inDegree.set(next, degree)
      if (degree === 0) {
        const nextIndex = indexOf.get(next) || 0
        let insertAt = 0
        while (insertAt < ready.length && (indexOf.get(ready[insertAt]) || 0) < nextIndex) insertAt++
        ready.splice(insertAt, 0, next)
      }
    }
  }

  if (ordered.length < allInPhase.length) {
    for (const eq of allInPhase) {
      if (!ordered.includes(eq)) ordered.push(eq)
    }
  }

  return ordered.filter(isVisibleRecipeEquation)
}

function extractTaskMediaIds(task: RecipeTask): number[] {
  const payload: any = task.payload || {}

  if (task.task_type === 'select') {
    const raw = Array.isArray(payload.candidates)
      ? payload.candidates
      : (Array.isArray(payload.options) ? payload.options : [])

    return raw
      .map((candidate: any) => {
        if (typeof candidate === 'number') return candidate
        if (candidate && typeof candidate === 'object') {
          const mediaId = candidate.media_id ?? candidate.mediaId ?? candidate.id ?? null
          return typeof mediaId === 'number' ? mediaId : null
        }
        return null
      })
      .filter((mediaId: number | null): mediaId is number => typeof mediaId === 'number' && Number.isFinite(mediaId))
  }

  if (task.task_type === 'approve') {
    const mediaId = payload.media_id ?? payload.mediaId ?? payload.asset?.media_id ?? payload.asset ?? null
    return typeof mediaId === 'number' && Number.isFinite(mediaId) ? [mediaId] : []
  }

  return []
}

function collectRecipeMediaIds(): number[] {
  const root = state.phaseTree.value?.root
  if (!root) return []

  const tasksByEquationKey = new Map<string, RecipeTask[]>()
  for (const task of state.tasks.value) {
    const tasks = tasksByEquationKey.get(task.equation_key) || []
    tasks.push(task)
    tasksByEquationKey.set(task.equation_key, tasks)
  }

  const orderedIds: number[] = []
  const seen = new Set<number>()
  const pushMediaIds = (mediaIds: number[] | null | undefined) => {
    for (const mediaId of mediaIds || []) {
      if (!Number.isFinite(mediaId) || seen.has(mediaId)) continue
      seen.add(mediaId)
      orderedIds.push(mediaId)
    }
  }

  const walkPhaseNode = (node: PhaseNodeType) => {
    const shouldIncludeDirectContent = node.path.length > 0 || node.children.length === 0
    if (shouldIncludeDirectContent) {
      for (const eq of getOrderedPhaseEquations(node.path || [])) {
        pushMediaIds(eq.result_media_ids)
        const tasks = tasksByEquationKey.get(eq.equation_key) || []
        for (const task of tasks) {
          pushMediaIds(extractTaskMediaIds(task))
        }
      }
    }

    for (const child of node.children || []) {
      walkPhaseNode(child)
    }
  }

  walkPhaseNode(root)
  return orderedIds
}

const recipeSlideshowMediaIds = computed(() => collectRecipeMediaIds())
let stopRecipeSlideshowListWatch: WatchStopHandle | null = null

function exitSlideshow(options?: { saveContext?: boolean }) {
  stopRecipeSlideshowListWatch?.()
  stopRecipeSlideshowListWatch = null
  exitBaseSlideshow(options)
}

function openRecipeMediaSlideshow(mediaId: number, options?: { mediaIds?: number[]; startIndex?: number }) {
  const seedIds = Array.isArray(options?.mediaIds)
    ? Array.from(new Set(options.mediaIds.filter((id) => Number.isFinite(id))))
    : []
  const fallbackIds = ref<number[]>(seedIds)
  const itemCache = new Map<number, any>()
  const locallyRemovedIds = ref<Set<number>>(new Set())
  const cacheVersion = ref(0)
  const notifyCacheChanged = () => { cacheVersion.value++ }
  const currentIds = computed(() => {
    void cacheVersion.value
    const ids = recipeSlideshowMediaIds.value.slice()
    for (const id of fallbackIds.value) {
      if (!ids.includes(id)) ids.push(id)
    }
    if (locallyRemovedIds.value.size === 0) return ids
    return ids.filter((id) => !locallyRemovedIds.value.has(id))
  })
  const startIds = currentIds.value
  const optionStartIndex = typeof options?.startIndex === 'number' ? options.startIndex : -1
  const startIndex = startIds.indexOf(mediaId)
  if (startIndex === -1) fallbackIds.value = [mediaId]
  if (currentIds.value.length === 0) return

  const resolvedStartIndex = startIndex >= 0 ? startIndex : optionStartIndex
  const clampedStartIndex = Math.max(0, Math.min(Math.max(resolvedStartIndex, 0), currentIds.value.length - 1))
  const mediaList = {
    totalCount: computed(() => currentIds.value.length),
    effectiveTotal: computed(() => currentIds.value.length),
    getItem(index: number) {
      void cacheVersion.value
      const id = currentIds.value[index]
      if (!Number.isFinite(id)) return null
      return itemCache.get(id) || null
    },
    async ensureItemLoaded(index: number) {
      const id = currentIds.value[index]
      if (!Number.isFinite(id) || itemCache.has(id)) return
      try {
        itemCache.set(id, await getMediaItem(id, { includeTrashed: true }))
      } catch {
        itemCache.set(id, {
          id,
          file_hash: null,
          _placeholder: true,
        })
      }
      notifyCacheChanged()
    },
    async loadPage(pageNumber: number, pageSize: number) {
      const start = pageNumber * pageSize
      const pageIds = currentIds.value.slice(start, start + pageSize)

      return await Promise.all(pageIds.map(async (id) => {
        if (itemCache.has(id)) return itemCache.get(id)
        try {
          const item = await getMediaItem(id, { includeTrashed: true })
          itemCache.set(id, item)
          notifyCacheChanged()
          return item
        } catch {
          const placeholder = {
            id,
            file_hash: null,
            _placeholder: true,
          }
          itemCache.set(id, placeholder)
          notifyCacheChanged()
          return placeholder
        }
      }))
    },
    findIndex(targetMediaId: number) {
      return currentIds.value.indexOf(targetMediaId)
    },
    removeItem(targetMediaId: number) {
      locallyRemovedIds.value = new Set([...locallyRemovedIds.value, targetMediaId])
      itemCache.delete(targetMediaId)
      notifyCacheChanged()
    },
    removeItems(targetMediaIds: number[]) {
      locallyRemovedIds.value = new Set([...locallyRemovedIds.value, ...targetMediaIds])
      for (const id of targetMediaIds) itemCache.delete(id)
      notifyCacheChanged()
    },
  }

  enterSlideshow({
    totalCount: currentIds.value.length,
    startIndex: clampedStartIndex,
    mediaList,
    randomized: false,
    randomSeed: null,
  })

  stopRecipeSlideshowListWatch?.()
  stopRecipeSlideshowListWatch = watch(currentIds, (ids) => {
    if (!slideshowState.active || slideshowState.mediaList !== mediaList) return
    slideshowState.totalCount = ids.length
    if (ids.length === 0) exitSlideshow()
  })
}

provide(recipeMediaSlideshowKey, {
  open: openRecipeMediaSlideshow,
})

// --- Control strip ---
const editingName = ref(false)
const editingNameValue = ref('')
const nameInputEl = ref<HTMLInputElement | null>(null)

function startEditName() {
  editingNameValue.value = recipe.value?.name || ''
  editingName.value = true
  nextTick(() => nameInputEl.value?.focus())
}
function cancelEditName() { editingName.value = false }
async function saveName() {
  const name = editingNameValue.value.trim()
  editingName.value = false
  if (!recipe.value) return
  if (name === (recipe.value.name || '')) return
  try { await state.updateMetadata({ name }) } catch (err) { console.error(err) }
}

const showStartButton  = computed(() => !recipe.value?.execution_state || recipe.value.execution_state === 'idle')
const showResumeButton = computed(() => recipe.value?.execution_state === 'paused')
const showPauseButton  = computed(() => recipe.value?.execution_state === 'running')

// Summary shown next to the "Steps" header: "N phases · Xs total". Only
// renders when the phase tree has top-level named phases — for a flat recipe
// with no named phases it'd read awkwardly. Uses the same duration visibility
// rules as graph/details and the phase rows.
const stepsSummary = computed<string | null>(() => {
  const root = state.phaseTree.value?.root
  if (!root) return null
  const phases = (root.children || []).length
  if (phases === 0) return null
  let totalMs = 0
  let any = false
  for (const eq of state.equationsByKey.value.values()) {
    const ms = equationDurationMs(eq)
    if (ms == null) continue
    totalMs += ms
    any = true
  }
  const parts = [phases === 1 ? '1 phase' : `${phases} phases`]
  if (any) {
    const dur = formatEquationDurationMs(totalMs)
    if (dur) parts.push(dur)
  }
  return parts.join(' · ')
})

// "All branches blocked" — the recipe is running, has failures, and nothing
// is actively making forward progress (no pending, no computing, no HITL
// awaiting input). The user must intervene (resolve an error task, edit the
// recipe via chat, or pause) to unstick it.
const allBlocked = computed<boolean>(() => {
  const summary = state.phaseTree.value?.root?.status_summary
  if (!summary) return false
  const failed = summary['failed'] || 0
  if (failed <= 0) return false
  const pending = summary['pending'] || 0
  const computing = summary['computing'] || 0
  const awaiting = summary['awaiting_input'] || 0
  return pending === 0 && computing === 0 && awaiting === 0
})

const parentName = ref<string | null>(null)

async function resolveParentName() {
  parentName.value = null
  const pid = recipe.value?.parent_id
  if (!pid) return
  try {
    const parent = await api.getRecipe(pid)
    parentName.value = parent.name || `Recipe #${pid}`
  } catch { parentName.value = `Recipe #${pid}` }
}
watch(() => recipe.value?.parent_id, () => resolveParentName(), { immediate: true })

function openParent() {
  if (recipe.value?.parent_id) router.push({ name: 'recipe', params: { id: String(recipe.value.parent_id) } })
}

// --- Copies dropdown ---
// Flat list of child recipes (parent_id == this recipe). Loaded eagerly on
// recipe change so we can hide the pill when there are zero copies, and
// refreshed on recipe_created / recipe_deleted WS events.
const copies = ref<Recipe[]>([])
const copiesLoading = ref(false)
const copiesOpen = ref(false)
const copiesRootEl = ref<HTMLElement | null>(null)

async function loadCopies() {
  if (!recipe.value) { copies.value = []; return }
  copiesLoading.value = true
  try {
    copies.value = await api.listRecipes({ parent_id: recipe.value.id })
  } catch { copies.value = [] }
  finally { copiesLoading.value = false }
}

function toggleCopies() {
  copiesOpen.value = !copiesOpen.value
}

function openCopy(c: Recipe) {
  copiesOpen.value = false
  router.push({ name: 'recipe', params: { id: String(c.id) } })
}

function copyStateBadge(state: string): string {
  switch (state) {
    case 'running': return 'bg-blue-500/20 text-blue-400'
    case 'paused': return 'bg-yellow-500/20 text-yellow-400'
    default: return 'bg-overlay-hover text-content-muted'
  }
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target
  if (!(target instanceof Node)) return
  if (copiesOpen.value) {
    const root = copiesRootEl.value
    if (root && !root.contains(target)) copiesOpen.value = false
  }
  if (showMenu.value) {
    const root = menuContainerRef.value
    if (root && !root.contains(target)) showMenu.value = false
  }
  if (showTabMenu.value) {
    const root = tabMenuContainerRef.value
    if (root && !root.contains(target)) showTabMenu.value = false
  }
  if (showChatMenu.value) {
    const root = chatMenuContainerRef.value
    if (root && !root.contains(target)) showChatMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
  stopRecipeSlideshowListWatch?.()
  stopRecipeSlideshowListWatch = null
})

watch(() => recipe.value?.id, (id) => {
  copiesOpen.value = false
  showMenu.value = false
  showTabMenu.value = false
  showChatMenu.value = false
  recipeChatSessions.value = []
  if (id) loadCopies()
  else copies.value = []
}, { immediate: true })

// --- 3-dot menu ---
const showMenu = ref(false)
const menuContainerRef = ref<HTMLElement | null>(null)
const showTabMenu = ref(false)
const tabMenuContainerRef = ref<HTMLElement | null>(null)

function toggleMenu() {
  showMenu.value = !showMenu.value
}

function toggleTabMenu() {
  showTabMenu.value = !showTabMenu.value
}

function handleRename() {
  showMenu.value = false
  startEditName()
}

function handleShowCodeIntroModal() {
  showTabMenu.value = false
  showCodeIntroModal.value = true
}

async function handleReparseRecipe() {
  showMenu.value = false
  showTabMenu.value = false
  await doReparseRecipe()
}

async function handleClearRecipe() {
  showMenu.value = false
  showTabMenu.value = false
  await doClearRecipe()
}

async function handleDelete() {
  showMenu.value = false
  if (!recipe.value) return
  const id = recipe.value.id
  try {
    await state.remove()
  } catch (err) {
    console.error('Failed to delete recipe:', err)
    addToast('Failed to delete recipe', 'error', 5000)
    return
  }
  router.push({ name: 'recipes' })
  addToast('Deleted 1 recipe', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      try {
        await api.restoreRecipe(id)
      } catch (err) {
        console.error('Failed to restore recipe:', err)
        addToast('Failed to restore recipe', 'error', 5000)
      }
    }
  })
}

// --- Chat menu (sessions + panel visibility) ---
type RecipeChatSession = { id: number; name: string; created_at: string; updated_at: string }

const showChatMenu = ref(false)
const chatMenuContainerRef = ref<HTMLElement | null>(null)
const recipeChatSessions = ref<RecipeChatSession[]>([])
const loadingChatSessions = ref(false)
const chatSessionsError = ref(false)
const creatingChatSession = ref(false)

async function loadChatSessions() {
  if (!recipe.value) return
  loadingChatSessions.value = true
  chatSessionsError.value = false
  try {
    const base = getApiBase()
    const response = await axios.get(`${base}/chats`, {
      params: { recipe_id: recipe.value.id, page: 1, page_size: 50 }
    })
    recipeChatSessions.value = (response.data?.items || []) as RecipeChatSession[]
  } catch (err) {
    console.error('Failed to load chat sessions:', err)
    chatSessionsError.value = true
  } finally {
    loadingChatSessions.value = false
  }
}

function toggleChatMenu() {
  showChatMenu.value = !showChatMenu.value
  if (showChatMenu.value) loadChatSessions()
}

async function handleNewChatSession() {
  if (creatingChatSession.value) return
  if (!recipe.value) return
  creatingChatSession.value = true
  try {
    const base = getApiBase()
    const created = await axios.post(`${base}/chats`, { recipe_id: recipe.value.id })
    const newId = created.data?.id
    if (newId) {
      recipeChatId.value = Number(newId)
      chatPanelOpen.value = true
    }
    showChatMenu.value = false
  } catch (err) {
    console.error('Failed to start new chat session:', err)
  } finally {
    creatingChatSession.value = false
  }
}

function handleSwitchChatSession(chatId: number) {
  if (chatId !== recipeChatId.value) {
    recipeChatId.value = chatId
    chatPanelOpen.value = true
  }
  showChatMenu.value = false
}

function handleToggleChatPanel() {
  chatPanelOpen.value = !chatPanelOpen.value
  showChatMenu.value = false
}

function sessionDisplayName(session: RecipeChatSession): string {
  const trimmed = (session.name || '').trim()
  if (trimmed) return trimmed
  try {
    const d = new Date(session.created_at)
    return `Session · ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
  } catch {
    return 'Untitled session'
  }
}

function formatSessionTime(iso: string): string {
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d`
  return date.toLocaleDateString()
}

// --- Execution controls ---
async function doPlay() {
  try {
    if (recipe.value?.execution_state === 'paused') {
      await state.resume()
    } else {
      await state.start()
    }
  } catch {
    // Error is surfaced via programLoadError in PhaseTree — no need to re-throw
  }
}
async function doPause() {
  try { await state.pause() } catch (err: any) { console.error('pause failed', err) }
}

// --- Invalidation ---
async function doInvalidateEquation(key: string) {
  try { await state.invalidateEquation(key) } catch (err) { console.error(err) }
}
async function doInvalidatePhase(path: string[]) {
  try { await state.invalidatePhase(path) } catch (err) { console.error(err) }
}
async function doReselectEquation(key: string, resolution: any) {
  try { await state.reselectEquation(key, resolution) } catch (err) { console.error(err) }
}

// --- Task resolution ---
async function onResolveTask(task: RecipeTask, resolution: any) {
  try {
    await state.resolveTask(task.task_id, resolution)
  } catch (err) { console.error('resolve failed', err) }
}
async function onResolveErrorTask(task: RecipeTask, action: string, value?: any) {
  try {
    await state.resolveErrorTask(task.task_id, action, value)
  } catch (err) { console.error('resolve-error failed', err) }
}

// --- Slideshow approval context ---
// When the slideshow is open inside a recipe, surface the approve task
// (or completed approve equation) for the currently displayed media so
// the slideshow can render its floating Approve / Replace / Unapprove
// bar. The approve equation's own result_media_ids may be empty, so we
// trace the candidate via its first dependency (the upstream producer).
type SlideshowApprovalState = 'awaiting' | 'approved' | 'pending' | 'failed'
interface SlideshowApprovalCtx {
  state: SlideshowApprovalState
  task: RecipeTask | null
  approveEquationKey: string
  replaceEquationKey: string | null
}

const slideshowApprovalContext = computed<SlideshowApprovalCtx | null>(() => {
  if (!slideshowState.active) return null
  const mid = slideshowState.currentMediaId
  if (typeof mid !== 'number' || !Number.isFinite(mid)) return null

  for (const task of state.tasks.value) {
    if (task.task_type !== 'approve' || task.status !== 'pending') continue
    if (!extractTaskMediaIds(task).includes(mid)) continue
    const eq = state.equationsByKey.value.get(task.equation_key)
    return {
      state: eq?.status === 'failed' ? 'failed' : 'awaiting',
      task,
      approveEquationKey: task.equation_key,
      replaceEquationKey: eq?.dependencies?.[0] ?? null,
    }
  }

  for (const eq of state.equationsByKey.value.values()) {
    if (eq.equation_type !== 'hitl' || eq.hitl_kind !== 'approve') continue
    const upstreamKey = eq.dependencies?.[0]
    const upstream = upstreamKey ? state.equationsByKey.value.get(upstreamKey) : null
    const candidateIds = upstream?.result_media_ids ?? eq.result_media_ids ?? []
    if (!candidateIds.includes(mid)) continue
    if (eq.status === 'failed') {
      return {
        state: 'failed',
        task: null,
        approveEquationKey: eq.equation_key,
        replaceEquationKey: slotWrapperKeyForApprove(eq.equation_key) ?? upstreamKey ?? null,
      }
    }
    if (eq.status === 'completed' && eq.result !== false) {
      return {
        state: 'approved',
        task: null,
        approveEquationKey: eq.equation_key,
        replaceEquationKey: slotWrapperKeyForApprove(eq.equation_key) ?? upstreamKey ?? null,
      }
    }
    return {
      state: 'awaiting',
      task: null,
      approveEquationKey: eq.equation_key,
      replaceEquationKey: upstreamKey ?? null,
    }
  }

  return null
})

async function onSlideshowApprove() {
  const ctx = slideshowApprovalContext.value
  if (!ctx) return
  try {
    if (ctx.task) {
      await state.resolveTask(ctx.task.task_id, true)
    } else if (ctx.state === 'awaiting') {
      await state.reselectEquation(ctx.approveEquationKey, true)
    }
  }
  catch (err) { console.error('slideshow approve failed', err) }
}
function slotWrapperKeyForApprove(approveEquationKey: string): string | null {
  const slash = approveEquationKey.lastIndexOf('/')
  return slash > 0 ? approveEquationKey.slice(0, slash) : null
}
async function onSlideshowReject() {
  const ctx = slideshowApprovalContext.value
  if (!ctx) return
  try {
    if (ctx.task) {
      await state.resolveTask(ctx.task.task_id, false)
    } else if (ctx.replaceEquationKey) {
      await state.invalidateEquation(ctx.replaceEquationKey)
    }
  }
  catch (err) { console.error('slideshow reject failed', err) }
}
async function onSlideshowUnapprove() {
  const ctx = slideshowApprovalContext.value
  if (!ctx?.approveEquationKey) return
  try { await state.invalidateEquation(ctx.approveEquationKey) }
  catch (err) { console.error('slideshow unapprove failed', err) }
}

// --- Input form ---
const submittingInputs = ref(false)
const inputFormRef = ref<InstanceType<typeof RecipeInputForm> | null>(null)
const inputsDirty = ref(false)
const inputsValid = ref(true)
const hasInputFields = computed(() => {
  const schema = recipe.value?.input_schema
  return !!schema && Object.keys(schema).length > 0
})
const showRecipeEmptyState = computed(() => {
  if (state.loadError.value || state.programLoadError.value || state.loading.value) return false
  const root = state.phaseTree.value?.root
  if (!root) return false
  return (root.equation_keys?.length ?? 0) === 0 && (root.children?.length ?? 0) === 0
})
const programAttentionError = computed(() => state.phaseTree.value?.load_error || state.programLoadError.value || null)
const failedRuntimeEquations = computed<RecipeEquation[]>(() =>
  Array.from(state.equationsByKey.value.values()).filter((eq) => eq.status === 'failed'),
)
const runtimeAttentionError = computed(() => {
  const failed = failedRuntimeEquations.value
  if (failed.length === 0) return null
  const firstWithError = failed.find((eq) => !!eq.error) || failed[0]
  const parsed = parseRecipeError(firstWithError.error)
  const stepName = firstWithError.display_name || firstWithError.phase_path?.slice(-1)[0] || 'step'
  return {
    category: parsed?.category || 'runtime_error',
    message: parsed?.message || `${stepName} failed. Ask the assistant to inspect the failed step and update the recipe.`,
    suggestion: null,
    failedCount: failed.length,
  }
})
const attentionError = computed(() => programAttentionError.value || runtimeAttentionError.value)
const attentionErrorSource = computed<'build' | 'runtime'>(() => programAttentionError.value ? 'build' : 'runtime')
const showRecipeAttentionBanner = computed(() => !!attentionError.value || allBlocked.value)

function resetInputsToDefaults() {
  showTabMenu.value = false
  inputFormRef.value?.resetToDefaults()
}

async function onInputSubmit(values: Record<string, any>) {
  if (!recipe.value) return
  submittingInputs.value = true
  try {
    await state.updateMetadata({ inputs: values })
  } catch (err) {
    console.error('Apply inputs failed:', err)
  } finally {
    submittingInputs.value = false
  }
}

// Workflow-view single-field input edit: the inspect panel emits a partial
// values map (one key for the selected recipe_input node). Merge it onto the
// recipe's existing inputs so the other fields keep their values, then write
// the whole blob back the same way the steps-view form does.
async function onPanelInputUpdate(partial: Record<string, any>) {
  if (!recipe.value) return
  const merged = { ...(recipe.value.inputs || {}), ...partial }
  submittingInputs.value = true
  try {
    await state.updateMetadata({ inputs: merged })
  } catch (err) {
    console.error('Apply input failed:', err)
  } finally {
    submittingInputs.value = false
  }
}

// --- Copy ---
const copying = ref(false)

async function doCopy() {
  if (!recipe.value) return
  showMenu.value = false
  copying.value = true
  try {
    const copy = await state.fork(recipe.value.inputs || {})
    router.push({ name: 'recipe', params: { id: String(copy.id) } })
  } catch (err) {
    console.error('Copy failed:', err)
  } finally {
    copying.value = false
  }
}

const isDev = devModeRef
const reparsingRecipe = ref(false)
const clearingRecipe = ref(false)
const codeViewRef = ref<InstanceType<typeof RecipeCodeView> | null>(null)
const codeDirty = ref(false)
const savingCode = ref(false)
const programCodeDraft = ref('')
const showCodeIntroModal = ref(false)

const codeErrors = useRecipeCodeErrors(state.programLoadError, state.equations)
const selectedCodeErrorId = ref<string | null>(null)

const selectedCodeError = computed(() =>
  codeErrors.value.find((e) => e.id === selectedCodeErrorId.value) ?? null,
)

const codeErrorLines = computed(() => {
  const err = selectedCodeError.value
  return err && err.line ? [err.line] : []
})

// Drop a stale selection when the underlying error list changes (recipe
// rebuilt, fix landed, etc.) so the editor doesn't keep highlighting a
// vanished error.
watch(codeErrors, (next) => {
  if (selectedCodeErrorId.value && !next.some((e) => e.id === selectedCodeErrorId.value)) {
    selectedCodeErrorId.value = null
  }
}, { deep: false })

function onSelectCodeError(id: string) {
  if (selectedCodeErrorId.value === id) {
    selectedCodeErrorId.value = null
    return
  }
  selectedCodeErrorId.value = id
  const err = codeErrors.value.find((e) => e.id === id)
  if (err?.line) codeViewRef.value?.scrollToLine(err.line)
}

function getProgramDraftKey(rid = recipeId.value) {
  return rid ? makeStorageKey('recipe', rid, 'program_draft') : null
}

function getCodeIntroKey() {
  return makeStorageKey('recipe', 'code_intro_seen')
}

function getStoredProgramDraft(rid = recipeId.value): string | null {
  const key = getProgramDraftKey(rid)
  if (!key) return null
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function clearStoredProgramDraft(rid = recipeId.value) {
  const key = getProgramDraftKey(rid)
  if (!key) return
  try { localStorage.removeItem(key) } catch {}
}

function handleCodeDraftUpdate(next: string) {
  programCodeDraft.value = next
  const key = getProgramDraftKey()
  if (!key) return
  try {
    if (next !== programCode.value) localStorage.setItem(key, next)
    else localStorage.removeItem(key)
  } catch {}
}

function revertCodeEdit() {
  clearStoredProgramDraft()
  programCodeDraft.value = programCode.value
  codeViewRef.value?.revertToOriginal()
  codeDirty.value = false
}

function dismissCodeIntro() {
  showCodeIntroModal.value = false
  try { localStorage.setItem(getCodeIntroKey(), 'true') } catch {}
}

function showCodeIntroIfNeeded() {
  try {
    if (localStorage.getItem(getCodeIntroKey()) === 'true') return
  } catch {}
  showCodeIntroModal.value = true
}

async function saveCodeEdit() {
  if (!recipeId.value || !codeViewRef.value) return
  const next = codeViewRef.value.getCurrentCode()
  if (savingCode.value || next === programCode.value) return
  savingCode.value = true
  try {
    const result = await api.updateProgramCode(recipeId.value, next)
    programCode.value = next
    programCodeDraft.value = next
    clearStoredProgramDraft()
    codeDirty.value = false
    // Reload the phase tree so the editor stays in sync with the rebuilt graph.
    await state.loadAll()
    if (result.load_error) {
      const msg = result.load_error.message || 'Recipe failed to compile'
      addToast(`Saved, but: ${msg}`, 'error', 8000)
    }
  } catch (err) {
    console.error('Save program failed:', err)
    addToast('Failed to save program.py', 'error', 5000)
  } finally {
    savingCode.value = false
  }
}

async function doReparseRecipe() {
  reparsingRecipe.value = true
  try {
    await state.reparse()
    if (viewMode.value === 'code') await loadProgramCode()
  } catch (err) {
    console.error('Re-parse failed:', err)
  } finally {
    reparsingRecipe.value = false
  }
}

async function doClearRecipe() {
  clearingRecipe.value = true
  try {
    await state.clear()
    focusedTaskId.value = null
    clearStoredProgramDraft()
    programCode.value = ''
    programCodeDraft.value = ''
    if (viewMode.value === 'code') await loadProgramCode()
  } catch (err) {
    console.error('Clear recipe failed:', err)
  } finally {
    clearingRecipe.value = false
  }
}

// --- Phase tree view mode ---
type RecipeViewMode = 'compact' | 'graph' | 'code'
const VIEW_MODE_KEY = 'recipe.viewMode'
const _storedViewMode = localStorage.getItem(VIEW_MODE_KEY)
const viewMode = ref<RecipeViewMode>(
  _storedViewMode === 'graph' || _storedViewMode === 'debug' ? 'graph'
  : _storedViewMode === 'code' ? 'code'
  : 'compact'
)
function toggleViewMode() {
  viewMode.value = viewMode.value === 'compact' ? 'graph' : 'compact'
  try { localStorage.setItem(VIEW_MODE_KEY, viewMode.value) } catch {}
}
function setViewMode(mode: RecipeViewMode) {
  viewMode.value = mode
  try { localStorage.setItem(VIEW_MODE_KEY, mode) } catch {}
  if (mode === 'code') {
    showCodeIntroIfNeeded()
    loadProgramCode()
  }
}

// Graph view: collapse foreach iterations into a single super-node (default)
// vs. render every iteration's equations as raw dagre nodes.
const GRAPH_COLLAPSE_KEY = 'recipe.graphCollapseForeach'
const graphCollapseForeach = ref<boolean>(
  localStorage.getItem(GRAPH_COLLAPSE_KEY) !== 'false',
)
watch(graphCollapseForeach, (v) => {
  try { localStorage.setItem(GRAPH_COLLAPSE_KEY, String(v)) } catch {}
})

// --- Program code (dev/code view) ---
const programCode = ref('')
const programCodeLoading = ref(false)
let programCodeLoadSeq = 0
async function loadProgramCode() {
  if (!recipeId.value) return
  const seq = ++programCodeLoadSeq
  const rid = recipeId.value
  programCodeLoading.value = true
  try {
    const code = await api.getProgramCode(recipeId.value)
    if (seq === programCodeLoadSeq) {
      programCode.value = code
      programCodeDraft.value = getStoredProgramDraft(rid) ?? code
    }
  } catch {
    if (seq === programCodeLoadSeq) {
      programCode.value = ''
      programCodeDraft.value = getStoredProgramDraft(rid) ?? ''
    }
  } finally {
    if (seq === programCodeLoadSeq) programCodeLoading.value = false
  }
}
watch([viewMode, recipeId], ([mode]) => {
  if (mode === 'code') {
    showCodeIntroIfNeeded()
    loadProgramCode()
  }
}, { immediate: true })
// Reload when program hash changes (agent wrote a new program)
watch(() => state.recipe.value?.program_hash, () => {
  if (viewMode.value === 'code') loadProgramCode()
})

// --- Chat sidebar (embedded ChatView scoped to this recipe) ---
// Open by default — a non-technical user needs the chat visible to understand
// that they drive the recipe through conversation.
const chatPanelOpen = ref(true)
const chatPanelWidth = ref(420)
const CHAT_MIN_WIDTH = 280
const CHAT_MAX_WIDTH = 700

function getChatPanelOpenKey(rid: string) {
  return makeStorageKey('recipe', rid, 'chat_panel_open')
}

function getChatPanelWidthKey(rid: string) {
  return makeStorageKey('recipe', rid, 'chat_panel_width')
}

watch(recipeId, (rid) => {
  if (!rid) return
  const openStored = localStorage.getItem(getChatPanelOpenKey(rid))
  chatPanelOpen.value = openStored === null ? true : openStored === 'true'
  const widthStored = localStorage.getItem(getChatPanelWidthKey(rid))
  if (widthStored !== null) {
    const parsed = Number(widthStored)
    if (Number.isFinite(parsed)) {
      chatPanelWidth.value = Math.min(CHAT_MAX_WIDTH, Math.max(CHAT_MIN_WIDTH, parsed))
    }
  }
}, { immediate: true })

watch(chatPanelOpen, (val) => {
  const rid = recipeId.value
  if (!rid) return
  localStorage.setItem(getChatPanelOpenKey(rid), String(val))
})

watch(chatPanelWidth, (val) => {
  const rid = recipeId.value
  if (!rid) return
  localStorage.setItem(getChatPanelWidthKey(rid), String(val))
})
let stopActiveChatResize: (() => void) | null = null

function startChatResize(e: MouseEvent) {
  e.preventDefault()
  stopActiveChatResize?.()
  const startX = e.clientX
  const startWidth = chatPanelWidth.value
  const previousUserSelect = document.body.style.userSelect
  const previousCursor = document.body.style.cursor
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  window.getSelection()?.removeAllRanges()

  function onMove(ev: MouseEvent) {
    ev.preventDefault()
    const delta = startX - ev.clientX
    chatPanelWidth.value = Math.min(CHAT_MAX_WIDTH, Math.max(CHAT_MIN_WIDTH, startWidth + delta))
  }
  function onUp() {
    document.body.style.userSelect = previousUserSelect
    document.body.style.cursor = previousCursor
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    stopActiveChatResize = null
  }
  stopActiveChatResize = onUp
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
onUnmounted(() => stopActiveChatResize?.())
const recipeChatId = ref<number | null>(null)
const chatLoading = ref(false)
const chatError = ref(false)

// Share the chat scope with phase-tree rows so they can attach references
// without each row getting a chat-id prop threaded through four components.
provide(RECIPE_CHAT_ID_KEY, recipeChatId)

function toggleChatPanel() { chatPanelOpen.value = !chatPanelOpen.value }

async function ensureRecipeChat() {
  if (!recipe.value) return
  const rid = recipe.value.id
  chatLoading.value = true
  chatError.value = false
  try {
    const base = getApiBase()
    const list = await axios.get(`${base}/chats`, { params: { recipe_id: rid, page: 1, page_size: 1 } })
    let chatId = list.data?.items?.[0]?.id
    if (!chatId) {
      const created = await axios.post(`${base}/chats`, { recipe_id: rid })
      chatId = created.data?.id
    }
    recipeChatId.value = chatId ? Number(chatId) : null
    if (!recipeChatId.value) chatError.value = true
  } catch (err) {
    console.error('Failed to open recipe chat:', err)
    chatError.value = true
  } finally {
    chatLoading.value = false
  }
}

// Re-resolve the chat whenever the recipe id changes (initial load or switching recipes).
watch(() => recipe.value?.id, (rid) => {
  recipeChatId.value = null
  chatError.value = false
  if (rid != null) ensureRecipeChat()
}, { immediate: true })

function openChatForEdit(_task: RecipeTask) {
  chatPanelOpen.value = true
}

// --- Ask-the-agent-to-fix flow ---
// Posts the current build error into the recipe-scoped chat so the agent
// sees it as a fresh user message and loops on it. The chat panel is opened
// (it should already be, by default) and the existing embedded ChatView
// stream shows the agent's response. We send via /chats/{id}/items rather
// than typing into the input box so this works even if the chat isn't
// currently focused.
const fixingWithAgent = ref(false)

// Agent-running signal for the recipe-scoped chat. We watch WS events for
// this chat id so the phase tree can render a soft "working on it" banner
// while the agent is iterating, instead of the red "not ready" alert.
const agentRunningInChat = ref(false)
const agentBusy = computed(() => agentRunningInChat.value || fixingWithAgent.value)

const { on: onWs } = useWebSocket()
let offAgentStarted: (() => void) | null = null
let offAgentStopped: (() => void) | null = null
let offWsDisconnected: (() => void) | null = null
let offWsReconnected: (() => void) | null = null
let offRecipeCreated: (() => void) | null = null
let offRecipeDeleted: (() => void) | null = null

async function syncRecipeAgentStatus() {
  if (recipeChatId.value == null) {
    agentRunningInChat.value = false
    return
  }
  try {
    const base = getApiBase()
    const response = await fetch(`${base}/chats/${recipeChatId.value}/plan-status`)
    if (!response.ok) return
    const data = await response.json()
    agentRunningInChat.value = Boolean(data?.has_plan && data?.status === 'running' && !data?.is_stale)
  } catch (error) {
    console.error('Failed to sync recipe agent status:', error)
  }
}

onMounted(() => {
  offAgentStarted = onWs('agent_started', (data: any) => {
    if (recipeChatId.value != null && data?.chat_id === recipeChatId.value) {
      agentRunningInChat.value = true
    }
  })
  offAgentStopped = onWs('agent_stopped', (data: any) => {
    if (recipeChatId.value != null && data?.chat_id === recipeChatId.value) {
      agentRunningInChat.value = false
    }
  })
  offWsDisconnected = onWs('websocket_disconnected', () => {
    agentRunningInChat.value = false
  })
  offWsReconnected = onWs('websocket_reconnected', () => {
    syncRecipeAgentStatus()
  })
  // Keep the Copies (N) header dropdown in sync as children appear or
  // disappear. New copies are only added as children of the current recipe;
  // deletes can affect this recipe's children regardless of which view
  // triggered them, so reload unconditionally.
  offRecipeCreated = onWs('recipe_created', (data: any) => {
    const parentId = data?.recipe?.parent_id
    if (recipe.value && parentId === recipe.value.id) loadCopies()
  })
  offRecipeDeleted = onWs('recipe_deleted', () => {
    if (recipe.value) loadCopies()
  })
})
onUnmounted(() => {
  offAgentStarted?.()
  offAgentStopped?.()
  offWsDisconnected?.()
  offWsReconnected?.()
  offRecipeCreated?.()
  offRecipeDeleted?.()
})

// Switching recipes (and thus chats) clears the running flag; the next
// agent_started for the new chat will flip it back on.
watch(recipeChatId, () => {
  agentRunningInChat.value = false
  syncRecipeAgentStatus()
})

async function askAgentToFix(_loadError: { category: string; message: string; suggestion?: string | null }) {
  chatPanelOpen.value = true
  if (!recipe.value) return
  if (recipeChatId.value == null) {
    await ensureRecipeChat()
    if (recipeChatId.value == null) return
  }
  fixingWithAgent.value = true
  try {
    const base = getApiBase()
    // Deliberately short and jargon-free — the assistant sees the real build
    // error via analyze_recipe, so we don't need to echo technical details
    // into the user-visible chat stream.
    const messageText = "This recipe isn't building — please take a look and fix it."
    await axios.post(`${base}/chats/${recipeChatId.value}/items`, {
      item_type: 'user_message',
      message_text: messageText,
    })
  } catch (err) {
    console.error('Failed to send fix request to agent:', err)
  } finally {
    fixingWithAgent.value = false
  }
}

async function handleAttentionFix() {
  if (programAttentionError.value) {
    await askAgentToFix(programAttentionError.value)
    return
  }
  await askAgentForHelpUnblocking()
}

async function askAgentForHelpUnblocking() {
  chatPanelOpen.value = true
  if (!recipe.value) return
  if (recipeChatId.value == null) {
    await ensureRecipeChat()
    if (recipeChatId.value == null) return
  }
  fixingWithAgent.value = true
  try {
    const base = getApiBase()
    // The assistant reads analyze_recipe for the real errors; this message
    // just points it at the failed runtime steps.
    const messageText = 'Some recipe steps failed. Please take a look and fix the recipe.'
    await axios.post(`${base}/chats/${recipeChatId.value}/items`, {
      item_type: 'user_message',
      message_text: messageText,
    })
  } catch (err) {
    console.error('Failed to send help request to agent:', err)
  } finally {
    fixingWithAgent.value = false
  }
}

async function askAgentToFixStep(equation: { display_name?: string | null; equation_key: string }) {
  chatPanelOpen.value = true
  if (!recipe.value) return
  if (recipeChatId.value == null) {
    await ensureRecipeChat()
    if (recipeChatId.value == null) return
  }
  try {
    const base = getApiBase()
    // Step-level fix request. The assistant reads analyze_recipe for the
    // actual error; the user message just points at which step failed.
    const label = equation.display_name || 'this step'
    const messageText = `The step "${label}" failed — please take a look and fix it.`
    await axios.post(`${base}/chats/${recipeChatId.value}/items`, {
      item_type: 'user_message',
      message_text: messageText,
    })
  } catch (err) {
    console.error('Failed to send step fix request to agent:', err)
  }
}

// --- Keyboard navigation over pending tasks ---
const focusedTaskId = ref<string | null>(null)
const taskRefs = new Map<string, any>()

function registerTaskRef(taskId: string, el: any) {
  if (el == null) { taskRefs.delete(taskId); return }
  taskRefs.set(taskId, el)
}

function orderedPendingTaskIds(): string[] {
  return state.tasks.value.map(t => t.task_id)
}

function currentIndex(ids: string[]): number {
  if (!focusedTaskId.value) return -1
  return ids.indexOf(focusedTaskId.value)
}

function focusTask(id: string | null) {
  focusedTaskId.value = id
  if (!id) return
  const ref = taskRefs.get(id)
  const el: HTMLElement | undefined = ref?.el?.value || ref?.el || null
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ block: 'nearest' })
  }
  if (el && typeof el.focus === 'function') el.focus({ preventScroll: true })
}

function nextTask() {
  const ids = orderedPendingTaskIds()
  if (ids.length === 0) return
  const cur = currentIndex(ids)
  focusTask(ids[(cur + 1) % ids.length])
}
function prevTask() {
  const ids = orderedPendingTaskIds()
  if (ids.length === 0) return
  const cur = currentIndex(ids)
  focusTask(ids[(cur - 1 + ids.length) % ids.length])
}

function handleKey(e: KeyboardEvent) {
  // Don't steal typing in inputs/textareas
  const target = e.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }
  if (e.key === 'Tab') return

  if (!focusedTaskId.value && e.key === 'ArrowDown') { nextTask(); e.preventDefault(); return }
  if (!focusedTaskId.value && e.key === 'ArrowUp') { prevTask(); e.preventDefault(); return }

  if (focusedTaskId.value) {
    const ref = taskRefs.get(focusedTaskId.value)
    if (ref?.handleKey) {
      const handled = ref.handleKey(e)
      if (handled) {
        e.preventDefault()
        return
      }
    }
  }
  if (e.key === 'j' || e.key === 'ArrowDown') { nextTask(); e.preventDefault() }
  else if (e.key === 'k' || e.key === 'ArrowUp') { prevTask(); e.preventDefault() }
}

onMounted(() => window.addEventListener('keydown', handleKey))
onUnmounted(() => window.removeEventListener('keydown', handleKey))

// Auto-focus first pending task when the list changes
watch(() => state.tasks.value.map(t => t.task_id).join(','), (_new) => {
  const ids = orderedPendingTaskIds()
  if (focusedTaskId.value && !ids.includes(focusedTaskId.value)) {
    focusedTaskId.value = ids[0] || null
  } else if (!focusedTaskId.value && ids.length > 0) {
    focusedTaskId.value = ids[0]
  }
})
</script>
