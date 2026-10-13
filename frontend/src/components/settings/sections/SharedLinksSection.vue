<template>
  <div data-testid="shared-links-section">
    <div class="mb-3">
      <h3 class="text-base font-medium text-content">Shared links</h3>
      <p class="mt-1 text-xs text-content-tertiary">Public links you’ve created. Anyone with a link can view the item.</p>
    </div>

    <div class="mt-6 max-w-[680px]">
      <div v-if="list.loading.value && !list.items.value.length" class="flex items-center gap-2 py-6" role="status">
        <Spinner hue="border-t-content-muted" />
        <span class="text-sm text-content-tertiary">Loading links…</span>
      </div>

      <!-- Signed out / expired -->
      <div v-else-if="reasonCode === 'signed_out' || reasonCode === 'auth_expired'" class="py-6">
        <p class="text-[13px] text-content">{{ reasonCode === 'auth_expired' ? 'Your sign-in expired' : 'Sign in to see your shared links' }}</p>
        <p class="mt-0.5 text-[11.5px] text-content-tertiary">Links are published from your Stimma account.</p>
        <button
          type="button"
          class="mt-4 inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-3 py-2 text-sm font-medium text-white transition-colors duration-150 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:cursor-not-allowed disabled:opacity-50 coarse:min-h-11"
          :disabled="signingIn"
          @click="signIn"
        >
          <Spinner v-if="signingIn" size="sm" hue="border-t-white" />
          {{ signingIn ? 'Finish signing in in your browser…' : reasonCode === 'auth_expired' ? 'Sign in again' : 'Sign in' }}
        </button>
        <p v-if="signInError" role="alert" class="mt-2 text-xs" :class="textClass('failed')">{{ signInError }}</p>
      </div>

      <!-- Privacy Lockdown -->
      <SettingRow v-else-if="reasonCode === 'privacy_lockdown'" label="Sharing is off in Privacy Lockdown" description="This install doesn’t contact Stimma services, so links can’t be listed or created." :divider="false">
        <Button variant="secondary" size="sm" class="coarse:min-h-11" @click="emit('navigate', 'privacy')">Privacy settings</Button>
      </SettingRow>

      <SettingRow v-else-if="reasonCode === 'unavailable' || (list.error.value && !list.items.value.length)" :label="list.error.value || 'Couldn’t reach Stimma'" description="Check your connection and try again." :divider="false">
        <Button variant="secondary" size="sm" class="coarse:min-h-11" @click="list.load()">Try again</Button>
      </SettingRow>

      <!-- Empty -->
      <div v-else-if="!list.items.value.length" class="py-10 text-center" data-testid="shared-links-empty">
        <LinkIcon class="mx-auto h-6 w-6 text-content-muted" :stroke-width="1.75" />
        <p class="mt-3 font-brand text-base font-semibold text-content">No shared links yet</p>
        <p class="mt-1 text-xs text-content-tertiary">Choose Share link… on any item to publish one.</p>
      </div>

      <!-- List -->
      <template v-else>
        <p v-if="reasonCode === 'banned'" class="mb-3 flex items-center gap-1.5 text-xs text-content-secondary">
          <StatusDot bucket="warning" />
          Sharing is suspended for this account. You can still delete links.
        </p>
        <ul class="divide-y divide-edge-subtle" data-testid="shared-links-list">
          <li v-for="link in list.items.value" :key="link.shortcode" class="flex items-center gap-3 py-2.5">
            <div class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-media bg-matte">
              <AppImage
                v-if="link.thumbnail_url"
                :src="link.thumbnail_url"
                alt=""
                container-class="h-10 w-10"
                img-class="h-10 w-10 object-cover"
                :draggable="false"
              />
              <component :is="typeIcon(link.media_type)" v-else class="h-4 w-4 text-content-muted" :stroke-width="1.75" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-[13px] text-content">{{ link.title || 'Untitled' }}</p>
              <p class="mt-0.5 flex items-center gap-1.5 truncate font-mono text-xs tabular-nums text-content-tertiary">
                <template v-if="isInReview(link.status)">
                  <StatusDot bucket="warning" />
                  <span class="font-sans">In review</span>
                  <span aria-hidden="true">·</span>
                </template>
                <span>{{ typeLabel(link.media_type) }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ viewsLabel(link.view_count) }}</span>
                <template v-if="link.created_at"><span aria-hidden="true">·</span><span>{{ formatDate(link.created_at) }}</span></template>
              </p>
            </div>
            <div class="flex items-center gap-0.5">
              <Tooltip :text="copiedCode === link.shortcode ? 'Copied' : 'Copy link'">
                <IconButton class="coarse:min-h-11 coarse:min-w-11" aria-label="Copy link" @click="copyLink(link)">
                  <CheckIcon v-if="copiedCode === link.shortcode" class="h-4 w-4" :stroke-width="1.75" />
                  <ClipboardDocumentIcon v-else class="h-4 w-4" :stroke-width="1.75" />
                </IconButton>
              </Tooltip>
              <Tooltip text="Open">
                <IconButton class="coarse:min-h-11 coarse:min-w-11" aria-label="Open link" @click="openUrl(link.url)">
                  <ArrowTopRightOnSquareIcon class="h-4 w-4" :stroke-width="1.75" />
                </IconButton>
              </Tooltip>
              <Tooltip text="Delete link">
                <IconButton variant="danger" class="coarse:min-h-11 coarse:min-w-11" aria-label="Delete link" @click="pendingDelete = link">
                  <TrashIcon class="h-4 w-4" :stroke-width="1.75" />
                </IconButton>
              </Tooltip>
            </div>
          </li>
          <li v-if="list.hasMore.value" class="py-2">
            <Button variant="ghost" size="sm" class="coarse:min-h-11" :loading="list.loadingMore.value" data-testid="shared-links-more" @click="list.loadMore()">Load more</Button>
          </li>
        </ul>
        <p v-if="list.error.value || deleteError" role="alert" class="mt-2 text-xs" :class="textClass('failed')">{{ deleteError || list.error.value }}</p>
      </template>
    </div>

    <ConfirmDialog
      :show="!!pendingDelete"
      title="Delete this link?"
      confirm-label="Delete link"
      danger
      nested
      :busy="deleting"
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    >
      “{{ pendingDelete?.title || 'Untitled' }}” will stop working for anyone who has the link. This can’t be undone.
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ArrowTopRightOnSquareIcon,
  CheckIcon,
  ClipboardDocumentIcon,
  CubeIcon,
  DocumentTextIcon,
  FilmIcon,
  LinkIcon,
  MusicalNoteIcon,
  PhotoIcon,
  Squares2X2Icon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import SettingRow from '../SettingRow.vue'
import Button from '../../ui/Button.vue'
import IconButton from '../../ui/IconButton.vue'
import Spinner from '../../ui/Spinner.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Tooltip from '../../ui/Tooltip.vue'
import ConfirmDialog from '../../ui/ConfirmDialog.vue'
import AppImage from '../../media/AppImage.vue'
import { createSharedLinksList, isInReview, type ShareLink } from '../../../composables/useShare'
import { useAuth } from '../../../composables/useAuth'
import { copyToClipboard } from '../../../utils/clipboard'
import { textClass } from '../../../utils/statusColors'

const emit = defineEmits<{ navigate: [section: string] }>()

const list = createSharedLinksList()
const { signInWithBrowser } = useAuth()
const reasonCode = computed(() => list.status.value?.reason_code ?? null)
const copiedCode = ref<string | null>(null)
const pendingDelete = ref<ShareLink | null>(null)
const deleting = ref(false)
const deleteError = ref('')
const signingIn = ref(false)
const signInError = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null

const TYPE_LABELS: Record<string, string> = {
  image: 'Image', video: 'Video', audio: 'Audio', text: 'Markdown', vector: 'SVG',
  sprite: 'Sprite', package: 'Package', set: 'Set', grid: 'Grid', layout: 'Layout',
}

function typeLabel(type: string | null) {
  return (type && TYPE_LABELS[type]) || 'Item'
}

function typeIcon(type: string | null) {
  switch (type) {
    case 'video': return FilmIcon
    case 'audio': return MusicalNoteIcon
    case 'text': return DocumentTextIcon
    case 'package': return CubeIcon
    case 'set': case 'grid': case 'layout': return Squares2X2Icon
    default: return PhotoIcon
  }
}

function viewsLabel(n: number) {
  return `${n.toLocaleString()} ${n === 1 ? 'view' : 'views'}`
}

function formatDate(value: string) {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString(undefined, sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' })
}

async function copyLink(link: ShareLink) {
  if (!(await copyToClipboard(link.url))) return
  copiedCode.value = link.shortcode
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copiedCode.value = null }, 2500)
}

async function openUrl(url: string) {
  try {
    const { desktop } = await import('../../../desktop')
    await desktop.openExternal(url)
  } catch {
    window.open(url, '_blank', 'noopener')
  }
}

async function confirmDelete() {
  const link = pendingDelete.value
  if (!link) return
  deleting.value = true
  deleteError.value = ''
  try {
    await list.remove(link.shortcode)
  } catch (err) {
    deleteError.value = (err as Error)?.message || 'Couldn’t delete that link'
  } finally {
    deleting.value = false
    pendingDelete.value = null
  }
}

async function signIn() {
  signingIn.value = true
  signInError.value = ''
  try {
    await signInWithBrowser('sign-in')
    await list.load()
  } catch (err) {
    signInError.value = (err as Error)?.message || 'Sign-in didn’t finish. Try again.'
  } finally {
    signingIn.value = false
  }
}

onMounted(() => { void list.load() })
</script>
