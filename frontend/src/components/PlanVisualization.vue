<template>
  <div class="plan-viz relative overflow-visible" ref="containerRef">
    <!-- SVG layer for edges -->
    <svg
      v-if="edgePaths.length"
      class="absolute top-0 left-0 pointer-events-none overflow-visible"
      :style="{ width: svgWidth + 'px', height: svgHeight + 'px' }"
    >
      <path
        v-for="edge in edgePaths"
        :key="`${edge.from}-${edge.to}`"
        :d="edge.path"
        fill="none"
        :stroke="isLight ? '#a1a1aa' : '#52525b'"
        stroke-width="1.5"
      />
    </svg>

    <!-- Layers of nodes -->
    <div class="relative z-10 space-y-6">
      <div
        v-for="(layer, layerIndex) in layout.layers"
        :key="layerIndex"
        class="flex justify-center items-start gap-4"
      >
        <div
          v-for="node in layer"
          :key="node.id"
          :ref="el => setNodeRef(node.id, el)"
          class="node-card rounded-lg border overflow-hidden w-fit max-w-[600px]"
          :class="getNodeCardClasses(node)"
        >
          <!-- Header -->
          <div class="flex items-center gap-2 px-3 py-2" :class="getNodeHeaderBg(node)">
            <!-- Status indicator -->
            <span class="shrink-0">
              <span v-if="getNodeStatus(node.id) === 'pending'" class="inline-block w-2 h-2 rounded-full bg-zinc-400"/>
              <svg v-else-if="getNodeStatus(node.id) === 'running'" class="w-4 h-4 animate-spin" :class="getNodeIconColor(node)" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-opacity="0.3"/>
                <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
              </svg>
              <svg v-else-if="getNodeStatus(node.id) === 'completed'" class="w-4 h-4 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
              </svg>
              <svg v-else-if="getNodeStatus(node.id) === 'failed'" class="w-4 h-4 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
              <svg v-else-if="getNodeStatus(node.id) === 'paused'" class="w-4 h-4 text-amber-500" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
              </svg>
            </span>

            <!-- Tool icon -->
            <component :is="getToolIcon(node)" class="w-4 h-4 shrink-0" :class="getNodeIconColor(node)" />

            <!-- Tool name + optional subtitle -->
            <div class="flex flex-col min-w-0">
              <span class="font-medium text-sm" :class="getNodeTextColor(node)">
                {{ getNodeDisplayName(node) }}
              </span>
              <span v-if="node.display_subtitle" class="text-[10px] text-content-tertiary">
                {{ node.display_subtitle }}
              </span>
            </div>

            <!-- Count badge for craft_prompts (in header) -->
            <span
              v-if="getCraftPromptsCount(node) > 1"
              class="ml-auto shrink-0 px-1.5 py-0.5 rounded bg-blue-500/20 text-[10px] font-medium"
              :class="isLight ? 'text-blue-700' : 'text-blue-500'"
            >x{{ getCraftPromptsCount(node) }}</span>
          </div>

          <!-- Progress bar for map nodes -->
          <div v-if="node.type === 'map' && getNodeProgress(node.id)" class="px-3 pb-2">
            <div class="flex items-center gap-2 text-[10px] text-content-tertiary mb-1">
              <span>{{ getNodeProgress(node.id).current }} / {{ getNodeProgress(node.id).total }}</span>
              <span class="text-content-secondary">{{ getNodeProgress(node.id).percentage }}%</span>
            </div>
            <div class="w-full h-1 bg-surface-raised rounded-full overflow-hidden">
              <div
                class="h-full bg-blue-500 transition-all duration-300"
                :style="{ width: getNodeProgress(node.id).percentage + '%' }"
              />
            </div>
          </div>

          <!-- Map details panel (always visible) -->
          <div v-if="node.type === 'map' && getMapIterationValues(node)" class="border-t border-edge-subtle px-3 py-2 bg-surface-overlay space-y-2">
            <!-- Iteration values -->
            <div class="text-xs">
              <div class="text-content-tertiary font-medium mb-1">Values:</div>
              <div class="text-content-secondary ml-3">
                <span v-for="(value, idx) in getMapIterationValues(node).slice(0, 20)" :key="idx">
                  {{ value }}<span v-if="idx < Math.min(19, getMapIterationValues(node).length - 1)">, </span>
                </span>
                <span v-if="getMapIterationValues(node).length > 20" class="text-content-tertiary"> ...and {{ getMapIterationValues(node).length - 20 }} more</span>
              </div>
            </div>

            <!-- Execution info -->
            <div class="text-xs space-y-0.5">
              <div>
                <span class="text-content-tertiary font-medium">Variable:</span>
                <span class="text-content-secondary ml-1.5 font-mono">{{ node.as_var || 'item' }}</span>
              </div>
              <div>
                <span class="text-content-tertiary font-medium">Mode:</span>
                <span class="text-content-secondary ml-1.5">{{ node.parallel ? 'Parallel' : 'Sequential' }}</span>
              </div>
            </div>
          </div>

          <!-- Body - only ref images and/or description text -->
          <div v-if="hasNodeBody(node)" class="px-3 py-2 space-y-2 bg-surface-overlay">
            <!-- Reference images -->
            <div v-if="getNodeImageIds(node).length" class="flex flex-wrap gap-1.5">
              <div
                v-for="mediaId in getNodeImageIds(node)"
                :key="mediaId"
                class="w-12 h-12 bg-surface-raised rounded border border-edge overflow-hidden flex items-center justify-center"
              >
                <MediaImage
                  :media-id="mediaId"
                  thumbnail
                  :thumbnail-size="128"
                  :draggable="false"
                  :enable-context-menu="false"
                  container-class="w-full h-full"
                  img-class="max-w-full max-h-full object-contain bg-checker"
                  :alt="`Reference image ${mediaId}`"
                />
              </div>
            </div>

            <!-- Description text -->
            <div v-if="getNodeDescription(node)" class="text-xs">
              <span class="text-content-secondary break-words leading-relaxed">"{{ getNodeDescription(node) }}"</span>
            </div>

            <!-- Prompts array (for generate with multiple prompts) -->
            <div v-if="getNodePrompts(node)" class="space-y-1.5">
              <div v-for="(p, i) in getNodePrompts(node)" :key="i" class="flex items-start gap-2">
                <span
                  v-if="p.count > 1"
                  class="shrink-0 px-1.5 py-0.5 rounded bg-blue-500/20 text-[10px] font-medium"
                  :class="isLight ? 'text-blue-700' : 'text-blue-500'"
                >x{{ p.count }}</span>
                <span class="text-content-secondary text-xs break-words leading-relaxed">"{{ p.text }}"</span>
              </div>
            </div>

            <!-- Tool parameters -->
            <div v-if="getToolArgs(node)" class="space-y-2">
              <div v-for="(arg, idx) in getToolArgs(node)" :key="idx">
                <!-- Simple text value -->
                <div v-if="arg.type === 'text'" class="text-xs">
                  <span class="text-content-tertiary font-medium">{{ arg.key }}:</span>
                  <span class="text-content-secondary ml-1.5">{{ arg.value }}</span>
                </div>

                <!-- Array value -->
                <div v-else-if="arg.type === 'array'" class="text-xs">
                  <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                  <ul class="ml-3 space-y-0.5">
                    <li v-for="(item, i) in arg.items" :key="i" class="text-content-secondary">
                      • {{ item.value }}
                    </li>
                  </ul>
                </div>

                <!-- Nested object value -->
                <div v-else-if="arg.type === 'nested'" class="text-xs">
                  <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                  <div class="ml-3 space-y-1">
                    <div v-for="(item, i) in arg.items" :key="i">
                      <!-- Nested text -->
                      <div v-if="item.type === 'text'">
                        <span class="text-content-tertiary">{{ item.key }}:</span>
                        <span class="text-content-secondary ml-1.5">{{ item.value }}</span>
                      </div>
                      <!-- Nested array -->
                      <div v-else-if="item.type === 'array'">
                        <div class="text-content-tertiary mb-0.5">{{ item.key }}:</div>
                        <ul class="ml-3 space-y-0.5">
                          <li v-for="(arrItem, j) in item.items" :key="j" class="text-content-secondary">
                            • {{ arrItem.value }}
                          </li>
                        </ul>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Nested body for map/loop - render as full cards -->
          <div v-if="node.body?.length" class="border-t border-edge-subtle px-3 py-2 space-y-2">
            <div
              v-for="child in node.body"
              :key="child.id"
              class="rounded-lg border overflow-hidden"
              :class="getNodeCardClasses(child)"
            >
              <!-- Child header (same as top-level) -->
              <div class="flex items-center gap-2 px-3 py-2" :class="getNodeHeaderBg(child)">
                <!-- Status indicator -->
                <span class="shrink-0">
                  <span v-if="getNodeStatus(child.id) === 'pending'" class="inline-block w-2 h-2 rounded-full bg-zinc-400"/>
                  <svg v-else-if="getNodeStatus(child.id) === 'running'" class="w-4 h-4 animate-spin" :class="getNodeIconColor(child)" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-opacity="0.3"/>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
                  </svg>
                  <svg v-else-if="getNodeStatus(child.id) === 'completed'" class="w-4 h-4 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                  </svg>
                  <svg v-else-if="getNodeStatus(child.id) === 'failed'" class="w-4 h-4 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
                  </svg>
                  <svg v-else-if="getNodeStatus(child.id) === 'paused'" class="w-4 h-4 text-amber-500" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                  </svg>
                </span>

                <!-- Tool icon -->
                <component :is="getToolIcon(child)" class="w-4 h-4 shrink-0" :class="getNodeIconColor(child)" />

                <!-- Tool name + optional subtitle -->
                <div class="flex flex-col min-w-0">
                  <span class="font-medium text-sm" :class="getNodeTextColor(child)">
                    {{ getNodeDisplayName(child) }}
                  </span>
                  <span v-if="child.display_subtitle" class="text-[10px] text-content-tertiary">
                    {{ child.display_subtitle }}
                  </span>
                </div>
              </div>

              <!-- Child body: reference images + tool args -->
              <div v-if="getNodeImageIds(child).length || getToolArgs(child)" class="px-3 py-2 bg-surface-overlay border-t border-edge-subtle space-y-2">
                <!-- Reference images -->
                <div v-if="getNodeImageIds(child).length" class="flex flex-wrap gap-1.5">
                  <div
                    v-for="mediaId in getNodeImageIds(child)"
                    :key="mediaId"
                    class="w-12 h-12 bg-surface-raised rounded border border-edge overflow-hidden flex items-center justify-center"
                  >
                    <MediaImage
                      :media-id="mediaId"
                      thumbnail
                      :thumbnail-size="128"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="w-full h-full"
                      img-class="max-w-full max-h-full object-contain bg-checker"
                      :alt="`Reference image ${mediaId}`"
                    />
                  </div>
                </div>
                <div v-for="(arg, idx) in getToolArgs(child)" :key="idx">
                  <!-- Simple text value -->
                  <div v-if="arg.type === 'text'" class="text-xs">
                    <span class="text-content-tertiary font-medium">{{ arg.key }}:</span>
                    <span class="text-content-secondary ml-1.5">{{ arg.value }}</span>
                  </div>

                  <!-- Array value -->
                  <div v-else-if="arg.type === 'array'" class="text-xs">
                    <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                    <ul class="ml-3 space-y-0.5">
                      <li v-for="(item, i) in arg.items" :key="i" class="text-content-secondary">
                        • {{ item.value }}
                      </li>
                    </ul>
                  </div>

                  <!-- Nested object value -->
                  <div v-else-if="arg.type === 'nested'" class="text-xs">
                    <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                    <div class="ml-3 space-y-1">
                      <div v-for="(item, i) in arg.items" :key="i">
                        <!-- Nested text -->
                        <div v-if="item.type === 'text'">
                          <span class="text-content-tertiary">{{ item.key }}:</span>
                          <span class="text-content-secondary ml-1.5">{{ item.value }}</span>
                        </div>
                        <!-- Nested array -->
                        <div v-else-if="item.type === 'array'">
                          <div class="text-content-tertiary mb-0.5">{{ item.key }}:</div>
                          <ul class="ml-3 space-y-0.5">
                            <li v-for="(arrItem, j) in item.items" :key="j" class="text-content-secondary">
                              • {{ arrItem.value }}
                            </li>
                          </ul>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Progress bar for nested map nodes -->
              <div v-if="child.type === 'map' && getNodeProgress(child.id)" class="px-3 pb-2">
                <div class="flex items-center gap-2 text-[10px] text-content-tertiary mb-1">
                  <span>{{ getNodeProgress(child.id).current }} / {{ getNodeProgress(child.id).total }}</span>
                  <span class="text-content-secondary">{{ getNodeProgress(child.id).percentage }}%</span>
                </div>
                <div class="w-full h-1 bg-surface-raised rounded-full overflow-hidden">
                  <div
                    class="h-full bg-blue-500 transition-all duration-300"
                    :style="{ width: getNodeProgress(child.id).percentage + '%' }"
                  />
                </div>
              </div>

              <!-- Details panel for nested map nodes (always visible) -->
              <div v-if="child.type === 'map' && getMapIterationValues(child)" class="border-t border-edge-subtle px-3 py-2 bg-surface-overlay space-y-2">
                <!-- Iteration values -->
                <div class="text-xs">
                  <div class="text-content-tertiary font-medium mb-1">Values:</div>
                  <div class="text-content-secondary ml-3">
                    <span v-for="(value, idx) in getMapIterationValues(child).slice(0, 20)" :key="idx">
                      {{ value }}<span v-if="idx < Math.min(19, getMapIterationValues(child).length - 1)">, </span>
                    </span>
                    <span v-if="getMapIterationValues(child).length > 20" class="text-content-tertiary"> ...and {{ getMapIterationValues(child).length - 20 }} more</span>
                  </div>
                </div>

                <!-- Execution info -->
                <div class="text-xs space-y-0.5">
                  <div>
                    <span class="text-content-tertiary font-medium">Variable:</span>
                    <span class="text-content-secondary ml-1.5 font-mono">{{ child.as_var || 'item' }}</span>
                  </div>
                  <div>
                    <span class="text-content-tertiary font-medium">Mode:</span>
                    <span class="text-content-secondary ml-1.5">{{ child.parallel ? 'Parallel' : 'Sequential' }}</span>
                  </div>
                </div>
              </div>

              <!-- Recursively render children of nested nodes (e.g., tool nodes inside nested maps) -->
              <div v-if="child.body?.length" class="border-t border-edge-subtle px-3 py-2 space-y-2">
                <div
                  v-for="grandchild in child.body"
                  :key="grandchild.id"
                  class="rounded-lg border overflow-hidden"
                  :class="getNodeCardClasses(grandchild)"
                >
                  <!-- Grandchild header -->
                  <div class="flex items-center gap-2 px-3 py-2" :class="getNodeHeaderBg(grandchild)">
                    <!-- Status indicator -->
                    <span class="shrink-0">
                      <span v-if="getNodeStatus(grandchild.id) === 'pending'" class="inline-block w-2 h-2 rounded-full bg-zinc-400"/>
                      <svg v-else-if="getNodeStatus(grandchild.id) === 'running'" class="w-4 h-4 animate-spin" :class="getNodeIconColor(grandchild)" viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-opacity="0.3"/>
                        <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
                      </svg>
                      <svg v-else-if="getNodeStatus(grandchild.id) === 'completed'" class="w-4 h-4 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                      </svg>
                      <svg v-else-if="getNodeStatus(grandchild.id) === 'failed'" class="w-4 h-4 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
                      </svg>
                      <svg v-else-if="getNodeStatus(grandchild.id) === 'paused'" class="w-4 h-4 text-amber-500" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                      </svg>
                    </span>

                    <!-- Tool icon -->
                    <component :is="getToolIcon(grandchild)" class="w-4 h-4 shrink-0" :class="getNodeIconColor(grandchild)" />

                    <!-- Tool name + optional subtitle -->
                    <div class="flex flex-col min-w-0">
                      <span class="font-medium text-sm" :class="getNodeTextColor(grandchild)">
                        {{ getNodeDisplayName(grandchild) }}
                      </span>
                      <span v-if="grandchild.display_subtitle" class="text-[10px] text-content-tertiary">
                        {{ grandchild.display_subtitle }}
                      </span>
                    </div>
                  </div>

                  <!-- Grandchild body: reference images + tool args -->
                  <div v-if="getNodeImageIds(grandchild).length || getToolArgs(grandchild)" class="px-3 py-2 bg-surface-overlay border-t border-edge-subtle space-y-2">
                    <!-- Reference images -->
                    <div v-if="getNodeImageIds(grandchild).length" class="flex flex-wrap gap-1.5">
                      <div
                        v-for="mediaId in getNodeImageIds(grandchild)"
                        :key="mediaId"
                        class="w-10 h-10 bg-surface-raised rounded border border-edge overflow-hidden flex items-center justify-center"
                      >
                        <MediaImage
                          :media-id="mediaId"
                          thumbnail
                          :thumbnail-size="128"
                          :draggable="false"
                          :enable-context-menu="false"
                          container-class="w-full h-full"
                          img-class="max-w-full max-h-full object-contain bg-checker"
                          :alt="`Reference image ${mediaId}`"
                        />
                      </div>
                    </div>
                    <div v-for="(arg, idx) in getToolArgs(grandchild)" :key="idx">
                      <!-- Simple text value -->
                      <div v-if="arg.type === 'text'" class="text-xs">
                        <span class="text-content-tertiary font-medium">{{ arg.key }}:</span>
                        <span class="text-content-secondary ml-1.5">{{ arg.value }}</span>
                      </div>

                      <!-- Array value -->
                      <div v-else-if="arg.type === 'array'" class="text-xs">
                        <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                        <ul class="ml-3 space-y-0.5">
                          <li v-for="(item, i) in arg.items" :key="i" class="text-content-secondary">
                            • {{ item.value }}
                          </li>
                        </ul>
                      </div>

                      <!-- Nested object value -->
                      <div v-else-if="arg.type === 'nested'" class="text-xs">
                        <div class="text-content-tertiary font-medium mb-0.5">{{ arg.key }}:</div>
                        <div class="ml-3 space-y-1">
                          <div v-for="(item, i) in arg.items" :key="i">
                            <!-- Nested text -->
                            <div v-if="item.type === 'text'">
                              <span class="text-content-tertiary">{{ item.key }}:</span>
                              <span class="text-content-secondary ml-1.5">{{ item.value }}</span>
                            </div>
                            <!-- Nested array -->
                            <div v-else-if="item.type === 'array'">
                              <div class="text-content-tertiary mb-0.5">{{ item.key }}:</div>
                              <ul class="ml-3 space-y-0.5">
                                <li v-for="(arrItem, j) in item.items" :key="j" class="text-content-secondary">
                                  • {{ arrItem.value }}
                                </li>
                              </ul>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, nextTick, onMounted, onUnmounted, watch } from 'vue'
import {
  SparklesIcon,
  PencilSquareIcon,
  FilmIcon,
  ArrowsPointingOutIcon,
  PhotoIcon,
  ScissorsIcon,
  MagnifyingGlassIcon,
  ChatBubbleLeftRightIcon,
  CalculatorIcon,
  DocumentTextIcon,
  ArrowPathIcon,
  FunnelIcon,
  Squares2X2Icon,
  QuestionMarkCircleIcon,
  CheckCircleIcon,
  ListBulletIcon,
  EyeIcon,
  CubeTransparentIcon,
  ViewfinderCircleIcon
} from '@heroicons/vue/24/outline'
import { MediaImage } from './media'
import { useTheme } from '../composables/useTheme'

const { resolvedTheme } = useTheme()
const isLight = computed(() => resolvedTheme.value === 'light')

const props = defineProps({
  plan: {
    type: Object,
    required: true
  },
  executionState: {
    type: Object,
    default: null
  }
})

const containerRef = ref(null)
const nodeRefs = ref({})
const svgWidth = ref(0)
const svgHeight = ref(0)
const edgePaths = ref([])

function setNodeRef(nodeId, el) {
  if (el) {
    nodeRefs.value[nodeId] = el
  }
}

// Context data for resolving ${...} references
const context = computed(() => props.plan._context || {})

/**
 * Compute DAG layout: assign each node to a layer based on longest path from roots.
 * Nodes in the same layer can run in parallel.
 */
const layout = computed(() => {
  const nodes = props.plan.nodes || []
  if (!nodes.length) return { layers: [], edges: [] }

  // Build adjacency structures
  const nodeMap = new Map()
  const inDegree = new Map()
  const outEdges = new Map() // node -> list of nodes that depend on it

  for (const node of nodes) {
    nodeMap.set(node.id, node)
    inDegree.set(node.id, (node.depends_on || []).length)
    outEdges.set(node.id, [])
  }

  // Build reverse edges (what depends on each node)
  for (const node of nodes) {
    for (const depId of (node.depends_on || [])) {
      if (outEdges.has(depId)) {
        outEdges.get(depId).push(node.id)
      }
    }
  }

  // Compute depth (longest path from any root) using topological traversal
  const depth = new Map()
  const queue = []

  // Start with roots (nodes with no dependencies)
  for (const node of nodes) {
    if (inDegree.get(node.id) === 0) {
      depth.set(node.id, 0)
      queue.push(node.id)
    }
  }

  // Process in topological order, updating depths
  while (queue.length > 0) {
    const nodeId = queue.shift()
    const currentDepth = depth.get(nodeId)

    for (const childId of outEdges.get(nodeId)) {
      // Child's depth is max of all incoming paths + 1
      const newDepth = currentDepth + 1
      depth.set(childId, Math.max(depth.get(childId) || 0, newDepth))

      // Decrease in-degree and add to queue if all deps processed
      inDegree.set(childId, inDegree.get(childId) - 1)
      if (inDegree.get(childId) === 0) {
        queue.push(childId)
      }
    }
  }

  // Group nodes by depth into layers
  const maxDepth = Math.max(...Array.from(depth.values()), 0)
  const layers = []
  for (let d = 0; d <= maxDepth; d++) {
    const layerNodes = nodes.filter(n => depth.get(n.id) === d)
    if (layerNodes.length > 0) {
      layers.push(layerNodes)
    }
  }

  // Collect edges with transitive reduction
  // If A -> B -> C and also A -> C, don't show A -> C (it's implied)
  const edges = []
  for (const node of nodes) {
    const deps = node.depends_on || []
    for (const depId of deps) {
      // Check if this edge is redundant (there's a path through another dep)
      const isRedundant = deps.some(otherDepId => {
        if (otherDepId === depId) return false
        // Check if depId is an ancestor of otherDepId
        const otherNode = nodeMap.get(otherDepId)
        if (!otherNode) return false
        // If otherNode depends on depId (directly or transitively), this edge is redundant
        const visited = new Set()
        const queue = [otherDepId]
        while (queue.length > 0) {
          const checkId = queue.shift()
          if (visited.has(checkId)) continue
          visited.add(checkId)
          const checkNode = nodeMap.get(checkId)
          if (!checkNode) continue
          for (const ancestorId of (checkNode.depends_on || [])) {
            if (ancestorId === depId) return true // Found path: depId -> ... -> otherDepId -> node
            queue.push(ancestorId)
          }
        }
        return false
      })

      if (!isRedundant) {
        edges.push({ from: depId, to: node.id, path: '' })
      }
    }
  }

  return { layers, edges, nodeMap, depth }
})

// Compute edge paths after DOM updates
async function updateEdgePaths() {
  await nextTick()

  if (!containerRef.value) return

  const containerRect = containerRef.value.getBoundingClientRect()

  const newEdges = []
  for (const edge of layout.value.edges) {
    const fromEl = nodeRefs.value[edge.from]
    const toEl = nodeRefs.value[edge.to]

    if (!fromEl || !toEl) continue

    const fromRect = fromEl.getBoundingClientRect()
    const toRect = toEl.getBoundingClientRect()

    // Calculate positions relative to container
    const fromX = fromRect.left - containerRect.left + fromRect.width / 2
    const fromY = fromRect.top - containerRect.top + fromRect.height

    const toX = toRect.left - containerRect.left + toRect.width / 2
    const toY = toRect.top - containerRect.top

    // Bezier curve from bottom of source to top of target
    const midY = (fromY + toY) / 2
    const path = `M ${fromX} ${fromY} C ${fromX} ${midY}, ${toX} ${midY}, ${toX} ${toY}`

    newEdges.push({ from: edge.from, to: edge.to, path })
  }

  // Update edge paths ref
  edgePaths.value = newEdges

  // Update SVG dimensions - use scrollHeight to include full content
  svgWidth.value = containerRef.value.scrollWidth
  svgHeight.value = containerRef.value.scrollHeight
}

let resizeObserver = null

onMounted(() => {
  // Delay initial edge computation to ensure DOM is ready
  // Two passes to handle late layout changes
  setTimeout(updateEdgePaths, 50)
  setTimeout(updateEdgePaths, 200)

  // Watch for container resize
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      updateEdgePaths()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})

watch(() => props.plan, () => {
  // Clear node refs since nodes may have changed
  nodeRefs.value = {}
  // Two passes to handle late layout changes
  setTimeout(updateEdgePaths, 100)
  setTimeout(updateEdgePaths, 300)
}, { deep: true })

watch(() => layout.value, () => {
  setTimeout(updateEdgePaths, 100)
  setTimeout(updateEdgePaths, 300)
})

// Get execution status for a node
function getNodeStatus(nodeId) {
  // If plan is interrupted/failed, show non-completed nodes as failed
  const planStatus = props.plan?.status
  if (planStatus === 'interrupted' || planStatus === 'failed') {
    const nodeStatus = props.executionState?.node_states?.[nodeId]?.status
    // Completed nodes stay completed, everything else shows as failed
    if (nodeStatus === 'completed') return 'completed'
    return 'failed'
  }

  if (!props.executionState?.node_states) return 'pending'
  return props.executionState.node_states[nodeId]?.status || 'pending'
}

// Get progress data for a node (used for map nodes)
function getNodeProgress(nodeId) {
  if (!props.executionState?.running_nodes) return null
  const runningNode = props.executionState.running_nodes.find(n => n.node_id === nodeId)
  if (runningNode && runningNode.current != null && runningNode.total != null) {
    return {
      current: runningNode.current,
      total: runningNode.total,
      percentage: Math.round((runningNode.current / runningNode.total) * 100)
    }
  }
  return null
}

// Get formatted iteration values for details panel
function getMapIterationValues(node) {
  if (!node.over || !Array.isArray(node.over)) return null

  return node.over.map(item => {
    if (typeof item === 'string') {
      return item
    } else if (typeof item === 'object' && item !== null) {
      // Extract value from common field names
      return item.value || item.label || item.name || item.text || String(item)
    }
    return String(item)
  })
}

// Tool name to display name mapping
const toolDisplayNames = {
  'generate': 'Generate Images',
  'edit_image': 'Edit Image',
  'image_to_video': 'Image to Video',
  'upscale_image': 'Upscale Image',
  'upscale_video': 'Upscale Video',
  'craft_prompts': 'Craft Prompts',
  'get_image_info': 'Get Image Info',
  'calculator': 'Calculator',
  'show_images': 'Show Images',
  'list_images': 'List Images',
  'request_approval': 'Request Approval',
  'present_choices': 'Present Choices',
  'get_feedback': 'Get Feedback',
  'ask_question': 'Ask Question',
  'find_objects': 'Find Objects',
  'interrogate': 'Interrogate Image',
  'get_alpha_bbox': 'Get Alpha Bounds',
  'crop_region': 'Crop Region',
  'remove_background': 'Remove Background',
}

// Tool icons mapping
const toolIcons = {
  'generate': SparklesIcon,
  'edit_image': PencilSquareIcon,
  'image_to_video': FilmIcon,
  'upscale_image': ArrowsPointingOutIcon,
  'upscale_video': ArrowsPointingOutIcon,
  'craft_prompts': DocumentTextIcon,
  'get_image_info': MagnifyingGlassIcon,
  'calculator': CalculatorIcon,
  'show_images': EyeIcon,
  'list_images': ListBulletIcon,
  'request_approval': CheckCircleIcon,
  'present_choices': Squares2X2Icon,
  'get_feedback': ChatBubbleLeftRightIcon,
  'ask_question': QuestionMarkCircleIcon,
  'find_objects': ViewfinderCircleIcon,
  'interrogate': MagnifyingGlassIcon,
  'get_alpha_bbox': CubeTransparentIcon,
  'crop_region': ScissorsIcon,
  'remove_background': CubeTransparentIcon,
}

function getToolIcon(node) {
  if (node.type === 'tool') {
    return toolIcons[node.tool_name] || SparklesIcon
  }
  switch (node.type) {
    case 'human': return ChatBubbleLeftRightIcon
    case 'loop': return ArrowPathIcon
    case 'map': return Squares2X2Icon
    case 'filter': return FunnelIcon
    default: return SparklesIcon
  }
}

function getNodeDisplayName(node) {
  // For tool nodes, use display_name from plan or fallback to mapping
  if (node.type === 'tool') {
    return node.display_name || toolDisplayNames[node.tool_name] || formatToolName(node.tool_name)
  }
  switch (node.type) {
    case 'human': {
      // Show the actual prompt for human nodes
      if (node.human_prompt) {
        // Truncate long prompts
        const prompt = node.human_prompt
        return prompt.length > 40 ? prompt.slice(0, 37) + '...' : prompt
      }
      // Fallback to display_name or action type
      if (node.display_name) return node.display_name
      const actionLabels = {
        'choose': 'Choose',
        'approve': 'Approve',
        'feedback': 'Give Feedback',
        'answer': 'Answer Question'
      }
      return actionLabels[node.human_action] || 'Human Action'
    }
    case 'loop': return node.display_name || 'Loop'
    case 'map': return node.display_name || 'For Each'
    case 'filter': return node.display_name || 'Filter'
    case 'accumulate': return node.display_name || 'Accumulate'
    default: return node.display_name || node.type || 'Unknown'
  }
}

function formatToolName(name) {
  if (!name) return 'Tool'
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}


// Determine if node needs a body section (ref images, description, prompts array, or tool args)
function hasNodeBody(node) {
  return getNodeImageIds(node).length > 0 || getNodeDescription(node) || getNodePrompts(node) || getToolArgs(node)
}

// Media ID fields that should never be shown (they're displayed as images instead)
const skipMediaFields = new Set([
  'media_id', 'media_ids', 'image_id', 'image_ids',
  'video_id', 'video_ids', 'reference_media_ids', 'source_media_id',
  'input_image', 'input_images', 'input_video', 'output_image', 'source_image',
  'input_media', 'output_media'
])
// Fields that are redundant with the node header display
const skipMetaFields = new Set(['tool_id'])

// Check if a field name + value looks like a media ID reference
function isMediaIdField(key, value) {
  if (typeof value !== 'number' && typeof value !== 'string') return false
  const num = typeof value === 'number' ? value : parseInt(value, 10)
  if (isNaN(num) || num <= 0) return false
  // Field name patterns that indicate media IDs
  const mediaPatterns = /(?:^|_)(image|media|video|audio|asset|photo)(?:_|$)/i
  return mediaPatterns.test(key)
}

// Get tool arguments to display (formatted for readability)
function getToolArgs(node) {
  if (node.type !== 'tool' || !node.tool_args) return null

  const formatted = []

  for (const [key, value] of Object.entries(node.tool_args)) {
    // Skip empty values and internal fields
    if (value === null || value === undefined || value === '' || key.startsWith('_')) continue
    // Skip large base64 images
    if (typeof value === 'string' && value.startsWith('data:image/')) continue
    // Skip media ID fields (shown as images)
    if (skipMediaFields.has(key)) continue
    // Skip fields redundant with header
    if (skipMetaFields.has(key)) continue
    // Skip values that look like bare media IDs in image/media-related fields
    if (isMediaIdField(key, value)) continue

    const arg = formatToolArg(key, value)
    if (arg) formatted.push(arg)
  }

  return formatted.length > 0 ? formatted : null
}

// Format a single tool argument for display
function formatToolArg(key, value) {
  // Handle nested parameters object
  if (key === 'parameters') {
    if (typeof value === 'object') {
      const items = []
      for (const [k, v] of Object.entries(value)) {
        // Apply the same media ID filtering to nested fields
        if (skipMediaFields.has(k)) continue
        if (skipMetaFields.has(k)) continue
        // Skip values that look like bare media IDs (numeric) in image/media-related fields
        if (isMediaIdField(k, v)) continue
        items.push(formatToolArg(k, v))
      }
      if (items.length === 0) return null
      return { key, type: 'nested', items }
    }
  }

  // Handle arrays (like loras)
  if (Array.isArray(value)) {
    const items = value.map((item, idx) => {
      if (typeof item === 'object') {
        // For loras, show path and weight
        if (item.path || item.name) {
          const path = item.path || item.name || item.label
          const weight = item.weight !== undefined ? item.weight : item.strength
          const label = weight !== undefined ? `${path} (${weight})` : path
          return { type: 'text', value: label }
        }
        // For other objects, try to find a meaningful label
        const label = item.label || JSON.stringify(item)
        return { type: 'text', value: label }
      }
      return { type: 'text', value: String(item) }
    })
    return { key, type: 'array', items }
  }

  // Handle strings
  if (typeof value === 'string') {
    let cleaned = value

    // Truncate very long strings but keep template variables visible
    if (cleaned.length > 300) {
      cleaned = cleaned.substring(0, 297) + '...'
    }

    return { key, type: 'text', value: cleaned }
  }

  // Handle numbers and booleans
  if (typeof value === 'number' || typeof value === 'boolean') {
    return { key, type: 'text', value: String(value) }
  }

  // Handle objects
  if (typeof value === 'object') {
    return { key, type: 'text', value: JSON.stringify(value) }
  }

  return { key, type: 'text', value: String(value) }
}

// Get description text for the body (edit prompts, instructions, etc.)
function getNodeDescription(node) {
  // Use explicit display_description if provided by planner
  if (node.display_description) return node.display_description

  // Show craft_prompts instruction in description
  if (node.type === 'agent' && node.agent_id === 'craft_prompts') {
    return node.agent_args?.instruction
  }

  if (node.type !== 'tool') return null
  const args = node.tool_args || {}

  // For edit_image, show the prompt as description
  if (node.tool_name === 'edit_image' && args.prompt) {
    const prompt = args.prompt
    // Skip template references - they come from craft_prompts shown elsewhere
    if (typeof prompt === 'string' && prompt.startsWith('${')) return null
    return prompt
  }

  return null
}

// Resolve ${...} references
function resolveRef(refString) {
  if (typeof refString !== 'string' || !refString.startsWith('${')) {
    return refString
  }

  const match = refString.match(/^\$\{(\w+)(?:\[(\d+)\])?(?:\.(\w+))?(?:\[(\d+)\])?(?:\.(\w+))?\}$/)
  if (!match) return refString

  const [, root, rootIdx, prop1, propIdx, prop2] = match
  let value = null

  if (root === 'selected' && context.value.selected) {
    value = context.value.selected
    if (rootIdx !== undefined) value = value[parseInt(rootIdx)]
  } else if (root === 'latest' && context.value.latest) {
    value = context.value.latest
    if (prop1 === 'items' && value.items) {
      value = value.items
      if (propIdx !== undefined) value = value[parseInt(propIdx)]
    }
  } else if (root === 'recent' && context.value.recent) {
    value = context.value.recent
    if (rootIdx !== undefined) value = value[parseInt(rootIdx)]
    if (prop1 === 'items' && value?.items) {
      value = value.items
      if (propIdx !== undefined) value = value[parseInt(propIdx)]
    }
  }

  const finalProp = prop2 || (propIdx !== undefined ? prop1 : null) || prop1
  if (value && finalProp && typeof value === 'object') {
    return value[finalProp]
  }

  return value
}

function getNodeImageIds(node) {
  if (node.type !== 'tool') return []
  const args = node.tool_args || {}

  const ids = []

  const addId = (val) => {
    if (typeof val === 'number') {
      ids.push(val)
    } else if (typeof val === 'string' && val.startsWith('${')) {
      const resolved = resolveRef(val)
      if (typeof resolved === 'number') ids.push(resolved)
    }
  }

  const addIds = (arr) => {
    if (Array.isArray(arr)) arr.forEach(addId)
  }

  addIds(args.image_ids)
  addId(args.image_id)
  addId(args.media_id)
  addIds(args.media_ids)
  addId(args.video_id)
  addIds(args.reference_media_ids)

  // Also check inside the nested parameters object
  const nested = args.parameters
  if (nested && typeof nested === 'object') {
    for (const [key, val] of Object.entries(nested)) {
      if (isMediaIdField(key, val)) {
        addId(val)
      } else if (Array.isArray(val)) {
        for (const item of val) {
          if (typeof item === 'number' || (typeof item === 'string' && item.startsWith('${'))) {
            addId(item)
          }
        }
      }
    }
  }

  return ids
}

function getNodePrompts(node) {
  if (node.type !== 'tool' || !node.tool_args?.prompts) return null
  return node.tool_args.prompts.map(p => ({
    count: p.n || 1,
    text: p.text || ''
  }))
}

// Get craft_prompts count for header badge
function getCraftPromptsCount(node) {
  if (node.type !== 'tool' || node.tool_name !== 'craft_prompts') return 0
  const args = node.tool_args || {}
  return args.count || 1
}

// Styling functions
function getNodeCardClasses(node) {
  const type = node.type
  const baseClasses = 'transition-colors'
  const light = isLight.value

  switch (type) {
    case 'tool':
      return `${baseClasses} ${light ? 'border-blue-500/40 bg-blue-500/10' : 'border-blue-500/30 bg-blue-500/5'}`
    case 'agent':
      return `${baseClasses} ${light ? 'border-violet-500/40 bg-violet-500/10' : 'border-violet-500/30 bg-violet-500/5'}`
    case 'human':
      return `${baseClasses} ${light ? 'border-amber-500/40 bg-amber-500/10' : 'border-amber-500/30 bg-amber-500/5'}`
    case 'loop':
      return `${baseClasses} ${light ? 'border-purple-500/40 bg-purple-500/10' : 'border-purple-500/30 bg-purple-500/5'}`
    case 'map':
      return `${baseClasses} ${light ? 'border-cyan-500/40 bg-cyan-500/10' : 'border-cyan-500/30 bg-cyan-500/5'}`
    case 'filter':
      return `${baseClasses} ${light ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-emerald-500/30 bg-emerald-500/5'}`
    default:
      return `${baseClasses} border-edge/50 bg-surface/50`
  }
}

function getNodeHeaderBg(node) {
  const type = node.type
  const light = isLight.value
  switch (type) {
    case 'tool': return light ? 'bg-blue-500/15' : 'bg-blue-500/10'
    case 'agent': return light ? 'bg-violet-500/15' : 'bg-violet-500/10'
    case 'human': return light ? 'bg-amber-500/15' : 'bg-amber-500/10'
    case 'loop': return light ? 'bg-purple-500/15' : 'bg-purple-500/10'
    case 'map': return light ? 'bg-cyan-500/15' : 'bg-cyan-500/10'
    case 'filter': return light ? 'bg-emerald-500/15' : 'bg-emerald-500/10'
    default: return 'bg-surface-raised/30'
  }
}

function getNodeIconColor(node) {
  const type = node.type
  const light = isLight.value
  switch (type) {
    case 'tool': return light ? 'text-blue-600' : 'text-blue-500'
    case 'agent': return light ? 'text-violet-600' : 'text-violet-500'
    case 'human': return light ? 'text-amber-600' : 'text-amber-500'
    case 'loop': return light ? 'text-purple-600' : 'text-purple-500'
    case 'map': return light ? 'text-cyan-600' : 'text-cyan-500'
    case 'filter': return light ? 'text-emerald-600' : 'text-emerald-500'
    default: return 'text-content-tertiary'
  }
}

function getNodeTextColor(node) {
  const type = node.type
  const light = isLight.value
  switch (type) {
    case 'tool': return light ? 'text-blue-700' : 'text-blue-500'
    case 'agent': return light ? 'text-violet-700' : 'text-violet-500'
    case 'human': return light ? 'text-amber-700' : 'text-amber-500'
    case 'loop': return light ? 'text-purple-700' : 'text-purple-500'
    case 'map': return light ? 'text-cyan-700' : 'text-cyan-500'
    case 'filter': return light ? 'text-emerald-700' : 'text-emerald-500'
    default: return 'text-content-secondary'
  }
}
</script>

<style scoped>
/* Node cards flex to fill available space */
</style>
