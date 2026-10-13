<template>
  <div v-if="inputs.length">
    <div class="text-xs text-content-tertiary mb-1.5">Inputs</div>
    <div class="flex flex-wrap gap-3">
      <div v-for="input in inputs" :key="input.key" class="flex flex-col" data-testid="provenance-input">
        <Tip :text="inputTitle(input)">
          <button
            type="button"
            class="relative block rounded-media overflow-hidden bg-matte p-0 border-none cursor-pointer transition-shadow hover:ring-1 hover:ring-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-default disabled:hover:ring-0"
            :class="size === 'sm' ? 'w-20 h-20' : 'w-24 h-24'"
            :disabled="!canOpen(input)"
            :aria-label="inputTitle(input)"
            @click="host.openInput?.(input)"
          >
            <!-- A preprocessed input shows what the tool saw; the host falls
                 back to the source while (or if) the preview can't be drawn. -->
            <component
              :is="host.thumbnail"
              :thumb-ref="input.preview || input.thumb"
              :fallback-ref="input.preview ? input.thumb : null"
              :alt="input.role"
              :size="size === 'sm' ? 80 : 96"
            />
            <div v-if="chips(input).length" class="absolute top-1 right-1 flex flex-col gap-0.5 items-end">
              <span
                v-for="chip in chips(input)"
                :key="chip"
                class="px-1.5 py-0.5 rounded-md bg-black/55 backdrop-blur-sm text-white text-[10px] leading-none"
              >{{ chip }}</span>
            </div>
          </button>
        </Tip>
        <!-- Actions under the thumbnail: open what it was made from, compare. -->
        <div v-if="actionsFor(input).length" class="flex justify-center gap-2 mt-1.5 text-[10px]">
          <template v-for="(action, i) in actionsFor(input)" :key="action.label">
            <span v-if="i > 0" class="text-content-muted">|</span>
            <button
              type="button"
              class="bg-transparent border-none p-0 cursor-pointer text-[10px] text-content-secondary hover:text-content transition-colors duration-150"
              @click="action.run()"
            >{{ action.label }}</button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Tip from './Tip.vue'
import { useProvenanceHost, type InputAction } from './host.ts'
import type { ViewInput } from './types.ts'

withDefaults(defineProps<{
  inputs: ViewInput[]
  size?: 'sm' | 'md'
}>(), {
  size: 'md',
})

const host = useProvenanceHost()

function chips(input: ViewInput): string[] {
  return [input.preprocessor, ...input.badges].filter((chip): chip is string => !!chip)
}

function inputTitle(input: ViewInput): string {
  return input.preprocessor ? `${input.role} · ${input.preprocessor}` : input.role
}

function canOpen(input: ViewInput): boolean {
  return !!host.openInput && (host.canOpenInput ? host.canOpenInput(input) : !input.deleted)
}

function actionsFor(input: ViewInput): InputAction[] {
  return host.inputActions ? host.inputActions(input) : []
}
</script>
