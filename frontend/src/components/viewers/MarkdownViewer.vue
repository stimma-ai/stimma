<template>
  <div class="w-full h-full overflow-auto p-8" :class="isDark ? 'bg-[#1e293b]' : 'bg-white'">
    <div v-if="loading" class="flex items-center justify-center h-full text-content-tertiary">
      Loading...
    </div>

    <div v-else-if="error" class="flex items-center justify-center h-full text-red-500">
      {{ error }}
    </div>

    <div v-else class="max-w-3xl mx-auto select-text">
      <!-- Title from frontmatter -->
      <h1 v-if="title" class="text-2xl font-semibold mb-2" :class="isDark ? 'text-slate-100' : 'text-gray-900'">{{ title }}</h1>

      <!-- Author from frontmatter -->
      <div v-if="author" class="text-sm mb-6" :class="isDark ? 'text-slate-400' : 'text-gray-500'">
        By {{ author }}
      </div>

      <!-- Rendered Markdown Content -->
      <div class="md-viewer-prose prose prose-slate max-w-none" :class="isDark ? 'prose-invert md-viewer-dark' : 'md-viewer-light'" v-html="renderedContent"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import axios from 'axios'
import { useMediaApi } from '../../composables/useMediaApi'
import { useTheme } from '../../composables/useTheme'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const { getMediaFileUrl } = useMediaApi()
const { resolvedTheme } = useTheme()
const isDark = computed(() => resolvedTheme.value === 'dark')

const loading = ref(true)
const error = ref(null)
const title = ref('')
const author = ref('')
const content = ref('')
const imageMap = ref({})  // Map from original path to resolved URL

async function loadContent() {
  loading.value = true
  error.value = null

  try {
    const response = await axios.get(`/api/media/${props.mediaId}/content`)
    const data = response.data

    // Extract frontmatter fields
    title.value = data.frontmatter?.title || ''
    author.value = data.frontmatter?.author || ''
    content.value = data.content || ''

    // Build URL map for resolved images
    const newImageMap = {}
    if (data.images && Array.isArray(data.images)) {
      for (const img of data.images) {
        if (img.resolved && img.resolved.file_hash) {
          // Use the media file URL for library images
          newImageMap[img.path] = getMediaFileUrl(img.resolved.file_hash)
        } else if (img.external) {
          // External URLs pass through
          newImageMap[img.path] = img.path
        }
        // Missing images will use original path (404) or could show placeholder
      }
    }
    imageMap.value = newImageMap

  } catch (e) {
    console.error('Failed to load markdown content:', e)
    error.value = 'Failed to load content'
  } finally {
    loading.value = false
  }
}

// Process markdown content and replace image paths with resolved URLs
const renderedContent = computed(() => {
  if (!content.value) return ''

  // Replace image paths in markdown before rendering
  let processedContent = content.value

  // Replace each image path with its resolved URL
  for (const [originalPath, resolvedUrl] of Object.entries(imageMap.value)) {
    // Escape special regex characters in the path
    const escapedPath = originalPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // Match the markdown image syntax with this path
    const regex = new RegExp(`!\\[([^\\]]*)\\]\\(${escapedPath}\\)`, 'g')
    processedContent = processedContent.replace(regex, `![$1](${resolvedUrl})`)
  }

  // Render markdown to sanitized HTML
  return renderSafeMarkdown(processedContent)
})

watch(() => props.mediaId, loadContent, { immediate: true })
</script>

<style>
.md-viewer-prose {
  line-height: 1.75;
}

.md-viewer-prose h1, .md-viewer-prose h2, .md-viewer-prose h3, .md-viewer-prose h4, .md-viewer-prose h5, .md-viewer-prose h6 {
  font-weight: 600;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
}

.md-viewer-prose h1 { font-size: 2em; }
.md-viewer-prose h2 { font-size: 1.5em; }
.md-viewer-prose h3 { font-size: 1.25em; }

.md-viewer-prose p { margin-bottom: 1em; }
.md-viewer-prose em { font-style: italic; }

.md-viewer-prose code {
  padding: 0.2em 0.4em;
  border-radius: 0.25rem;
  font-size: 0.875em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.md-viewer-prose pre {
  border-radius: 0.5rem;
  padding: 1em;
  overflow-x: auto;
  margin: 1em 0;
}

.md-viewer-prose pre code { background-color: transparent; padding: 0; }
.md-viewer-prose ul, .md-viewer-prose ol { margin: 1em 0; padding-left: 1.5em; }
.md-viewer-prose ul { list-style-type: disc; }
.md-viewer-prose ol { list-style-type: decimal; }
.md-viewer-prose li { margin: 0.25em 0; }

.md-viewer-prose blockquote {
  border-left-width: 4px;
  padding-left: 1em;
  margin: 1em 0;
  font-style: italic;
}

.md-viewer-prose hr { border: none; margin: 2em 0; }
.md-viewer-prose img { max-width: 100%; height: auto; border-radius: 0.5rem; margin: 1em 0; }
.md-viewer-prose table { width: 100%; border-collapse: collapse; margin: 1em 0; }
.md-viewer-prose th, .md-viewer-prose td { padding: 0.5em 0.75em; text-align: left; }
.md-viewer-prose th { font-weight: 600; }

/* Dark theme */
.md-viewer-dark { color: #e2e8f0; }
.md-viewer-dark h1, .md-viewer-dark h2, .md-viewer-dark h3,
.md-viewer-dark h4, .md-viewer-dark h5, .md-viewer-dark h6 { color: #f1f5f9; }
.md-viewer-dark strong { color: #f1f5f9; }
.md-viewer-dark a { color: #60a5fa; text-decoration: underline; }
.md-viewer-dark a:hover { color: #93c5fd; }
.md-viewer-dark code { background-color: #334155; }
.md-viewer-dark pre { background-color: #1e293b; border: 1px solid #334155; }
.md-viewer-dark blockquote { border-left-color: #475569; color: #94a3b8; }
.md-viewer-dark hr { border-top: 1px solid #475569; }
.md-viewer-dark th, .md-viewer-dark td { border: 1px solid #475569; }
.md-viewer-dark th { background-color: #334155; }

/* Light theme */
.md-viewer-light { color: #1e293b; }
.md-viewer-light h1, .md-viewer-light h2, .md-viewer-light h3,
.md-viewer-light h4, .md-viewer-light h5, .md-viewer-light h6 { color: #111827; }
.md-viewer-light strong { color: #111827; }
.md-viewer-light a { color: #2563eb; text-decoration: underline; }
.md-viewer-light a:hover { color: #1d4ed8; }
.md-viewer-light code { background-color: #f1f5f9; }
.md-viewer-light pre { background-color: #f8fafc; border: 1px solid #d1d5db; }
.md-viewer-light blockquote { border-left-color: #d1d5db; color: #6b7280; }
.md-viewer-light hr { border-top: 1px solid #d1d5db; }
.md-viewer-light th, .md-viewer-light td { border: 1px solid #d1d5db; }
.md-viewer-light th { background-color: #f1f5f9; }
</style>
