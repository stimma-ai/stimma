<template>
  <component
    :is="isCompact ? Sheet : Modal"
    :show="visible"
    v-bind="shellProps"
    @close="requestClose"
  >
    <template v-if="!isCompact" #header>
      <div class="flex items-center justify-between gap-3">
        <h2 class="text-base font-semibold text-content">{{ heading }}</h2>
        <IconButton aria-label="Close" class="coarse:min-h-11 coarse:min-w-11 -mr-1.5" :disabled="busy" @click="requestClose">
          <XMarkIcon class="w-5 h-5" :stroke-width="1.75" />
        </IconButton>
      </div>
    </template>

    <div data-share-dialog :data-share-phase="session.phase.value" class="flex flex-col">
      <!-- Loading ------------------------------------------------------------ -->
      <div v-if="session.phase.value === 'loading' || session.phase.value === 'idle'" class="flex min-h-[240px] items-center justify-center gap-2 px-6 py-5" role="status">
        <Spinner hue="border-t-content-muted" />
        <span class="text-sm text-content-tertiary">Checking your account…</span>
      </div>

      <!-- Can't share -------------------------------------------------------- -->
      <template v-else-if="session.phase.value === 'cant-share'">
        <div class="flex min-h-[220px] flex-col items-center justify-center px-6 py-6 text-center compact:px-4">
          <div class="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-overlay-subtle text-content-secondary">
            <component :is="blockedCopy.icon" class="h-5 w-5" :stroke-width="1.75" />
          </div>
          <p class="text-sm font-medium text-content">{{ blockedCopy.title }}</p>
          <p class="mt-1 max-w-[340px] text-xs leading-relaxed text-content-tertiary">{{ blockedCopy.body }}</p>
          <p v-if="signInError" role="alert" class="mt-2 text-xs" :class="textClass('failed')">{{ signInError }}</p>
          <div class="mt-5">
            <button
              v-if="blockedCopy.action === 'sign-in'"
              type="button"
              data-testid="share-sign-in"
              class="inline-flex items-center justify-center gap-1.5 rounded-md bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface disabled:cursor-not-allowed disabled:opacity-50 coarse:min-h-11"
              :disabled="signingIn"
              @click="signIn"
            >
              <Spinner v-if="signingIn" size="sm" hue="border-t-white" />
              {{ signingIn ? 'Finish signing in in your browser…' : blockedCopy.actionLabel }}
            </button>
            <Button v-else-if="blockedCopy.action === 'privacy'" variant="secondary" class="coarse:min-h-11" @click="openSettingsSection('privacy')">
              Open Privacy settings
            </Button>
            <Button v-else-if="blockedCopy.action === 'retry'" variant="secondary" class="coarse:min-h-11" @click="session.recheck()">
              Try again
            </Button>
          </div>
        </div>
        <div :class="FOOTER">
          <span />
          <Button variant="secondary" :class="COARSE" @click="requestClose">Close</Button>
        </div>
      </template>

      <!-- Username setup ----------------------------------------------------- -->
      <template v-else-if="session.phase.value === 'username'">
        <form class="px-6 py-5 compact:px-4" @submit.prevent="session.submitUsername()">
          <p class="text-sm font-medium text-content">Choose a username</p>
          <p class="mt-1 text-xs leading-relaxed text-content-tertiary">It appears on every link you share.</p>
          <label class="mt-4 block">
            <span class="sr-only">Username</span>
            <span class="relative flex items-center">
              <span class="pointer-events-none absolute left-3 font-mono text-sm text-content-muted">@</span>
              <input
                :value="session.usernameInput.value"
                type="text"
                inputmode="text"
                autocomplete="off"
                autocapitalize="off"
                spellcheck="false"
                maxlength="24"
                placeholder="username"
                data-testid="share-username"
                :disabled="session.usernameSubmitting.value"
                :class="[INPUT, 'pl-7 pr-9 font-mono']"
                @input="session.setUsername(($event.target as HTMLInputElement).value)"
              />
              <span v-if="session.usernameChecking.value" class="absolute right-3"><Spinner size="sm" hue="border-t-content-muted" /></span>
            </span>
          </label>
          <p class="mt-2 flex min-h-[18px] items-center gap-1.5 text-xs" aria-live="polite">
            <template v-if="session.usernameError.value">
              <StatusDot bucket="failed" />
              <span :class="textClass('failed')">{{ session.usernameError.value }}</span>
            </template>
            <template v-else-if="session.usernameAvailable.value === true">
              <StatusDot bucket="done" />
              <span class="text-content-secondary">Available</span>
            </template>
            <template v-else>
              <span class="text-content-tertiary">3–24 characters: lowercase letters, numbers, - and _</span>
            </template>
          </p>
          <button type="submit" class="hidden" />
        </form>
        <div :class="FOOTER">
          <span />
          <div class="flex items-center gap-2">
            <Button variant="ghost" :class="COARSE" :disabled="session.usernameSubmitting.value" @click="requestClose">Cancel</Button>
            <Button
              :class="COARSE"
              data-testid="share-username-continue"
              :disabled="!session.canSubmitUsername.value"
              :loading="session.usernameSubmitting.value"
              @click="session.submitUsername()"
            >Continue</Button>
          </div>
        </div>
      </template>

      <!-- Existing links for this item --------------------------------------- -->
      <template v-else-if="session.phase.value === 'links'">
        <div class="px-6 pt-4 pb-2 compact:px-4">
          <p class="text-xs font-semibold text-content-secondary">
            {{ session.links.value.length === 1 ? 'This item already has a link' : `This item has ${session.links.value.length} links` }}
          </p>
          <ul class="mt-1 divide-y divide-edge-subtle" data-testid="share-existing-links">
            <li v-for="link in session.links.value" :key="link.shortcode" class="flex items-center gap-3 py-2.5">
              <div class="min-w-0 flex-1">
                <p class="truncate text-[13px] text-content">{{ link.title || 'Untitled' }}</p>
                <p class="mt-0.5 flex items-center gap-1.5 font-mono text-xs tabular-nums text-content-tertiary">
                  <template v-if="isInReview(link.status)">
                    <StatusDot bucket="warning" />
                    <span class="font-sans">In review</span>
                    <span aria-hidden="true">·</span>
                  </template>
                  <span>{{ viewsLabel(link.view_count) }}</span>
                  <template v-if="link.created_at"><span aria-hidden="true">·</span><span>{{ formatDate(link.created_at) }}</span></template>
                  <span aria-hidden="true">·</span><span class="truncate">{{ link.shortcode }}</span>
                </p>
              </div>
              <div class="flex items-center gap-0.5">
                <Tooltip :text="copiedCode === link.shortcode ? 'Copied' : 'Copy link'">
                  <IconButton :class="COARSE_ICON" :aria-label="`Copy link ${link.title || ''}`" @click="copyLink(link.url, link.shortcode)">
                    <CheckIcon v-if="copiedCode === link.shortcode" class="h-4 w-4" :stroke-width="1.75" />
                    <ClipboardDocumentIcon v-else class="h-4 w-4" :stroke-width="1.75" />
                  </IconButton>
                </Tooltip>
                <Tooltip text="Open">
                  <IconButton :class="COARSE_ICON" aria-label="Open link" @click="openUrl(link.url)">
                    <ArrowTopRightOnSquareIcon class="h-4 w-4" :stroke-width="1.75" />
                  </IconButton>
                </Tooltip>
                <Tooltip text="Delete link">
                  <IconButton variant="danger" :class="COARSE_ICON" aria-label="Delete link" @click="pendingDelete = link">
                    <TrashIcon class="h-4 w-4" :stroke-width="1.75" />
                  </IconButton>
                </Tooltip>
              </div>
            </li>
          </ul>
          <p v-if="deleteError" role="alert" class="pt-1 text-xs" :class="textClass('failed')">{{ deleteError }}</p>
        </div>
        <div :class="FOOTER">
          <PublishingAccount :account="session.account.value" />
          <div class="flex items-center gap-2">
            <Button variant="ghost" :class="COARSE" @click="requestClose">Close</Button>
            <Button :class="COARSE" data-testid="share-create-another" @click="session.createAnother()">Create another link</Button>
          </div>
        </div>
      </template>

      <!-- Form + uploading --------------------------------------------------- -->
      <template v-else-if="session.phase.value === 'form' || session.phase.value === 'uploading'">
        <div class="px-6 pt-5 pb-3 compact:px-4 compact:pt-2">
          <div class="flex h-44 items-center justify-center overflow-hidden rounded-media bg-matte compact:h-36" data-testid="share-preview">
            <MediaImage
              v-if="media"
              :media-id="media.id"
              :file-hash="(media.file_hash as string | undefined) || undefined"
              :file-format="String(media.file_format || '')"
              :is-video="!!media.is_video"
              :is-audio="mediaType === 'audio'"
              :has-alpha="(media.has_alpha as boolean | null | undefined) ?? null"
              :thumbnail-size="512"
              thumbnail-mode="fit"
              contain
              :draggable="false"
              :enable-context-menu="false"
              background-class="bg-matte"
              container-class="h-full w-full"
              loading="eager"
            />
          </div>
          <p class="mt-2 font-mono text-xs tabular-nums text-content-tertiary" data-testid="share-type-fact">{{ typeFact }}</p>

          <div class="mt-4 space-y-2">
            <label class="relative block">
              <span class="sr-only">Title</span>
              <input
                :value="session.title.value"
                type="text"
                maxlength="100"
                data-testid="share-title"
                :placeholder="session.suggesting.value ? 'Suggesting a title…' : 'Title'"
                :disabled="uploading"
                :class="[INPUT, session.suggesting.value ? 'pr-9' : '']"
                @input="session.setTitle(($event.target as HTMLInputElement).value)"
              />
              <span v-if="session.suggesting.value" class="absolute right-3 top-1/2 -translate-y-1/2" aria-label="Suggesting a title">
                <Spinner size="sm" hue="border-t-content-muted" />
              </span>
            </label>
            <label class="block">
              <span class="sr-only">Description</span>
              <textarea
                v-model="session.description.value"
                maxlength="500"
                rows="2"
                placeholder="Description (optional)"
                data-testid="share-description"
                :disabled="uploading"
                :class="[INPUT, 'resize-none']"
              />
            </label>
          </div>

          <div class="mt-3 divide-y divide-edge-subtle">
            <div v-if="stepCount > 0">
              <SettingRow label="Include how it was made" :divider="false">
                <template #description>
                  <span>{{ stepCount === 1 ? 'Publishes 1 step' : `Publishes ${stepCount} steps` }}: tools, prompts and settings.</span>
                  <button
                    type="button"
                    class="ml-1 inline-flex items-center gap-0.5 text-content-secondary underline-offset-2 hover:text-content hover:underline focus-visible:outline-none focus-visible:ring-2 ring-accent/60 rounded-md coarse:min-h-11"
                    :aria-expanded="provenanceOpen"
                    data-testid="share-provenance-toggle"
                    @click="provenanceOpen = !provenanceOpen"
                  >
                    {{ provenanceOpen ? 'Hide' : 'Show what’s published' }}
                    <ChevronDownIcon class="h-3 w-3 transition-transform duration-150" :class="provenanceOpen ? 'rotate-180' : ''" :stroke-width="1.75" />
                  </button>
                </template>
                <Toggle v-model="session.includeProvenance.value" label="Include how it was made" :disabled="uploading" />
              </SettingRow>
              <div
                v-if="provenanceOpen"
                class="mb-2.5 max-h-56 space-y-3 overflow-y-auto rounded-md bg-overlay-faint px-3 py-2.5 custom-scrollbar"
                :class="session.includeProvenance.value ? '' : 'opacity-50'"
                data-testid="share-provenance-preview"
              >
                <div v-for="(step, i) in publishedSteps" :key="i" class="min-w-0">
                  <p class="flex items-baseline justify-between gap-2 text-xs">
                    <span class="truncate font-medium text-content">{{ step.tool }}</span>
                    <span v-if="step.model && step.model !== step.tool" class="truncate font-mono text-[11px] text-content-tertiary">{{ step.model }}</span>
                  </p>
                  <p v-if="step.prompt" class="mt-0.5 line-clamp-2 text-xs text-content-secondary">{{ step.prompt }}</p>
                  <p v-if="step.facts.length" class="mt-0.5 font-mono text-[11px] tabular-nums text-content-tertiary">{{ step.facts.join(' · ') }}</p>
                  <p v-if="step.extras.length" class="mt-0.5 text-[11px] text-content-tertiary">{{ step.extras.join(' · ') }}</p>
                </div>
              </div>
            </div>
            <SettingRow label="Mark as mature" :divider="false">
              <template #description>
                {{ session.matureLocked.value ? 'Detected automatically. Viewers see a content warning first.' : 'Viewers see a content warning first.' }}
              </template>
              <Toggle
                :model-value="session.mature.value"
                label="Mark as mature"
                :disabled="session.matureLocked.value || uploading"
                data-testid="share-mature"
                @update:model-value="session.matureManual.value = $event"
              />
            </SettingRow>
          </div>

          <p class="mt-2 flex min-h-[20px] items-start gap-2 text-xs" aria-live="polite" data-testid="share-status-slot" :data-slot="session.statusSlot.value || ''">
            <template v-if="session.statusSlot.value === 'checking'">
              <Spinner size="sm" hue="border-t-content-muted" class="mt-0.5" />
              <span class="text-content-tertiary">Checking content…</span>
            </template>
            <template v-else-if="session.statusSlot.value">
              <StatusDot :bucket="slotCopy.bucket" class="mt-1.5" />
              <span :class="slotCopy.bucket === 'failed' ? textClass('failed') : 'text-content-secondary'">{{ slotCopy.text }}</span>
            </template>
          </p>
        </div>
        <div :class="FOOTER">
          <PublishingAccount :account="session.account.value" />
          <div class="flex items-center gap-2">
            <Button variant="ghost" :class="COARSE" :disabled="uploading" @click="requestClose">Cancel</Button>
            <Button
              :class="COARSE"
              data-testid="share-create"
              :disabled="!session.canCreate.value && !uploading"
              :loading="uploading"
              @click="session.create()"
            >{{ uploading ? uploadingLabel : 'Create link' }}</Button>
          </div>
        </div>
      </template>

      <!-- Created ------------------------------------------------------------ -->
      <template v-else-if="session.phase.value === 'created' && session.result.value">
        <div class="px-6 py-5 compact:px-4">
          <p class="flex items-center gap-2 text-sm font-medium text-content">
            <StatusDot :bucket="createdInReview ? 'warning' : 'done'" />
            {{ createdInReview ? 'Link created, in review' : 'Link created' }}
          </p>
          <p class="mt-1 text-xs leading-relaxed text-content-tertiary">
            <template v-if="createdInReview">It will be visible to others once the review finishes. You can copy the link now.</template>
            <template v-else>Anyone with the link can view it.</template>
          </p>
          <input
            :value="session.result.value.url"
            readonly
            data-testid="share-link-url"
            aria-label="Link"
            :class="[INPUT, 'mt-4 font-mono text-xs select-all']"
            @focus="($event.target as HTMLInputElement).select()"
          />
          <div class="mt-2 flex items-center gap-2">
            <Button variant="secondary" size="sm" :class="COARSE" data-testid="share-copy" @click="copyLink(session.result.value.url, session.result.value.shortcode)">
              <template #icon>
                <CheckIcon v-if="copiedCode === session.result.value.shortcode" class="h-4 w-4" :stroke-width="1.75" />
                <ClipboardDocumentIcon v-else class="h-4 w-4" :stroke-width="1.75" />
              </template>
              {{ copiedCode === session.result.value.shortcode ? 'Copied' : 'Copy' }}
            </Button>
            <Button variant="secondary" size="sm" :class="COARSE" @click="openUrl(session.result.value.url)">
              <template #icon><ArrowTopRightOnSquareIcon class="h-4 w-4" :stroke-width="1.75" /></template>
              Open
            </Button>
          </div>
        </div>
        <div :class="FOOTER">
          <PublishingAccount :account="session.account.value" />
          <Button :class="COARSE" @click="requestClose">Done</Button>
        </div>
      </template>

      <!-- Error -------------------------------------------------------------- -->
      <template v-else-if="session.phase.value === 'error'">
        <div class="flex min-h-[200px] flex-col items-center justify-center px-6 py-6 text-center compact:px-4">
          <div class="mb-3 flex h-10 w-10 items-center justify-center rounded-full" :class="bgClass('failed')">
            <ExclamationTriangleIcon class="h-5 w-5" :class="textClass('failed')" :stroke-width="1.75" />
          </div>
          <p class="text-sm font-medium text-content">Couldn’t create the link</p>
          <p class="mt-1 max-w-[340px] text-xs leading-relaxed text-content-tertiary" data-testid="share-error">{{ session.error.value }}</p>
        </div>
        <div :class="FOOTER">
          <Button variant="ghost" :class="COARSE" @click="session.backToForm()">Back</Button>
          <div class="flex items-center gap-2">
            <Button variant="ghost" :class="COARSE" @click="requestClose">Cancel</Button>
            <Button :class="COARSE" data-testid="share-retry" @click="session.create()">Try again</Button>
          </div>
        </div>
      </template>
    </div>
  </component>

  <ConfirmDialog
    :show="!!pendingDelete"
    title="Delete this link?"
    confirm-label="Delete link"
    danger
    nested
    :over-sheet="isCompact"
    :busy="deleting"
    @confirm="confirmDelete"
    @cancel="pendingDelete = null"
  >
    Anyone who has it will no longer be able to open it. This can’t be undone.
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, ref, shallowRef, watch, type PropType } from 'vue'
import {
  ArrowTopRightOnSquareIcon,
  CheckIcon,
  ChevronDownIcon,
  ClipboardDocumentIcon,
  ExclamationTriangleIcon,
  LinkIcon,
  NoSymbolIcon,
  ShieldCheckIcon,
  TrashIcon,
  WifiIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import Modal from './ui/Modal.vue'
import Sheet from './ui/Sheet.vue'
import Button from './ui/Button.vue'
import IconButton from './ui/IconButton.vue'
import Spinner from './ui/Spinner.vue'
import StatusDot from './ui/StatusDot.vue'
import Tooltip from './ui/Tooltip.vue'
import Toggle from './ui/Toggle.vue'
import ConfirmDialog from './ui/ConfirmDialog.vue'
import SettingRow from './settings/SettingRow.vue'
import MediaImage from './media/MediaImage.vue'
import AppImage from './media/AppImage.vue'
import { useViewport } from '../composables/useViewport'
import { useShareDialog } from '../composables/useShareDialog'
import { useShare, isInReview, formatBytes, publishedStepsPreview, shareTypeFact, type ShareAccount, type ShareLink, type ShareMedia } from '../composables/useShare'
import { useProvenanceBuilder } from '../composables/useMediaProvenance'
import { publicStepCount, toPublicProvenance, type MediaLike, type PublicProvenance } from '../utils/mediaProvenance'
import { useMediaApi } from '../composables/useMediaApi'
import { useAuth } from '../composables/useAuth'
import { copyToClipboard } from '../utils/clipboard'
import { getMediaType } from '../utils/mediaTypes'
import { bgClass, textClass, type StatusBucket } from '../utils/statusColors'

const INPUT = 'w-full rounded-md border border-transparent bg-overlay-subtle px-3 py-2 text-sm text-content placeholder:text-content-muted outline-none transition-colors duration-150 focus:border-accent focus-visible:ring-2 ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50 compact:text-[15px]'
const FOOTER = 'flex items-center justify-between gap-3 border-t border-edge px-6 py-4 compact:px-4 compact:py-3'
const COARSE = 'coarse:min-h-11'
const COARSE_ICON = 'coarse:min-h-11 coarse:min-w-11'

// The account that will publish: the serving machine's, from /api/share/status.
const PublishingAccount = defineComponent({
  props: { account: { type: Object as PropType<ShareAccount | null>, default: null } },
  setup(props) {
    // An account can point at an avatar that no longer exists; fall back to
    // the initial rather than a broken-image glyph.
    const failedAvatar = ref<string | null>(null)
    return () => {
      const a = props.account
      if (!a?.username) return h('span')
      const initial = (a.display_name || a.username || '?').charAt(0).toUpperCase()
      return h('div', { class: 'flex min-w-0 items-center gap-2', 'data-testid': 'share-account', title: a.display_name || undefined }, [
        a.avatar_url && failedAvatar.value !== a.avatar_url
          ? h(AppImage, { src: a.avatar_url, alt: '', class: 'h-5 w-5 shrink-0 overflow-hidden rounded-full', containerClass: 'h-5 w-5 rounded-full', imgClass: 'h-5 w-5 rounded-full object-cover', draggable: false, onError: () => { failedAvatar.value = a.avatar_url } })
          : h('span', { class: 'flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-overlay-light text-[10px] font-medium text-content-secondary', 'aria-hidden': 'true' }, initial),
        h('span', { class: 'truncate font-mono text-xs text-content-secondary' }, `@${a.username}`),
      ])
    }
  },
})

const { isCompact } = useViewport()
const dialog = useShareDialog()
const { getMediaItem } = useMediaApi()
const { signInWithBrowser } = useAuth()

const { build: buildProvenance } = useProvenanceBuilder()
const session = useShare({ buildPublicProvenance: (item) => toPublicProvenance(buildProvenance(item as MediaLike)) })
const media = shallowRef<ShareMedia | null>(null)
const animationCount = ref<number | null>(null)
const provenanceOpen = ref(false)
const copiedCode = ref<string | null>(null)
const pendingDelete = ref<ShareLink | null>(null)
const deleting = ref(false)
const deleteError = ref('')
const signingIn = ref(false)
const signInError = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null
let autoCopied = false
let loadToken = 0

const visible = computed(() => dialog.state.value.visible)
const uploading = computed(() => session.phase.value === 'uploading')
const busy = computed(() => uploading.value || deleting.value)

const shellProps = computed(() => isCompact.value
  ? { title: heading.value, closeOnBackdrop: !busy.value }
  : { size: 'md', closeOnBackdrop: !busy.value, closeOnEsc: !busy.value })

const heading = computed(() => {
  switch (session.phase.value) {
    case 'username': return 'Set up sharing'
    case 'created': return 'Link ready'
    default: return 'Share link'
  }
})

const mediaType = computed(() => media.value ? getMediaType({ file_format: String(media.value.file_format || '') }) : 'image')
const typeFact = computed(() => shareTypeFact(media.value as any, { animationCount: animationCount.value, sizeBytes: session.preCheck.value?.size_bytes ?? null }))
const stepCount = computed(() => publicStepCount(session.provenance.value as PublicProvenance | null))
const publishedSteps = computed(() => publishedStepsPreview(session.provenance.value))
const uploadingLabel = computed(() => {
  const size = formatBytes(session.sizeBytes.value)
  return size ? `Uploading ${size}…` : 'Uploading…'
})
const createdInReview = computed(() => isInReview(session.result.value?.status))

const blockedCopy = computed(() => {
  const code = session.reasonCode.value
  switch (code) {
    case 'signed_out':
      return { icon: LinkIcon, title: 'Sign in to share links', body: 'Links are published from your Stimma account. Anyone with a link can view the item.', action: 'sign-in', actionLabel: 'Sign in' }
    case 'auth_expired':
      return { icon: LinkIcon, title: 'Your sign-in expired', body: 'Sign in again to publish links from your Stimma account.', action: 'sign-in', actionLabel: 'Sign in again' }
    case 'privacy_lockdown':
      return { icon: ShieldCheckIcon, title: 'Sharing is off in Privacy Lockdown', body: 'Privacy Lockdown keeps this install from contacting Stimma services, so links can’t be published.', action: 'privacy', actionLabel: '' }
    case 'banned':
      return { icon: NoSymbolIcon, title: 'Sharing is suspended for this account', body: session.status.value?.reason && !/suspended/i.test(session.status.value.reason) ? session.status.value.reason : 'Links can’t be created from this account. Your existing links are listed in Settings.', action: null, actionLabel: '' }
    default:
      return { icon: WifiIcon, title: 'Couldn’t check your account', body: 'Stimma didn’t answer. Check your connection and try again.', action: 'retry', actionLabel: '' }
  }
})

const slotCopy = computed<{ bucket: StatusBucket; text: string }>(() => {
  const p = session.preCheck.value
  switch (session.statusSlot.value) {
    case 'review':
      return { bucket: 'warning', text: p?.reason || 'This may be held for review before others can see it.' }
    case 'blocked':
      return { bucket: 'failed', text: p?.reason || 'This can’t be shared under the content policy.' }
    case 'too-large': {
      const size = formatBytes(p?.size_bytes)
      return { bucket: 'failed', text: p?.reason || (size ? `Too large to share as a link (${size}; the limit is 95 MB).` : 'Too large to share as a link (the limit is 95 MB).') }
    }
    case 'unsupported':
      return { bucket: 'failed', text: p?.unsupported_reason || 'This kind of item can’t be shared as a link yet.' }
    default:
      return { bucket: 'queued', text: '' }
  }
})

function viewsLabel(n: number) {
  return `${n.toLocaleString()} ${n === 1 ? 'view' : 'views'}`
}

function formatDate(value: string) {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString(undefined, sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' })
}

async function loadMedia(mediaId: number, seed: ShareMedia | null) {
  const token = ++loadToken
  media.value = seed
  animationCount.value = null
  provenanceOpen.value = false
  autoCopied = false
  copiedCode.value = null
  deleteError.value = ''
  signInError.value = ''
  let item: ShareMedia | null = seed
  try {
    item = await getMediaItem(mediaId)
  } catch {
    // Keep the caller's copy; the session still works from the id.
  }
  if (token !== loadToken) return
  const full = item ?? { id: mediaId }
  media.value = full
  void session.start(full)
  if (getMediaType({ file_format: String(full.file_format || '') }) === 'sprite') void loadSpriteFacts(full.id, token)
}

async function loadSpriteFacts(id: number, token: number) {
  try {
    const response = await fetch(`/api/media/${id}/content`)
    if (!response.ok) return
    const data = await response.json()
    if (token !== loadToken) return
    const names = new Set((data?.animations || []).map((a: { name?: string }) => a?.name).filter(Boolean))
    animationCount.value = names.size || null
  } catch { /* the fact just stays "Sprite" */ }
}

watch(() => dialog.state.value.openCount, () => {
  const s = dialog.state.value
  if (s.visible && s.mediaId) void loadMedia(s.mediaId, (s.media as ShareMedia | null) ?? { id: s.mediaId })
})

watch(visible, (open) => {
  if (!open) {
    loadToken++
    session.dispose()
    pendingDelete.value = null
  }
})

// Created: copy once, automatically.
watch(() => session.phase.value, (phase) => {
  if (phase === 'created' && session.result.value && !autoCopied) {
    autoCopied = true
    void copyLink(session.result.value.url, session.result.value.shortcode)
  }
})

function requestClose() {
  if (busy.value) return
  dialog.close()
}

async function copyLink(url: string, code: string) {
  if (!url) return
  const ok = await copyToClipboard(url)
  if (!ok) return
  copiedCode.value = code
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copiedCode.value = null }, 2500)
}

async function openUrl(url: string) {
  if (!url) return
  try {
    const { desktop } = await import('../desktop')
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
    await session.deleteLink(link.shortcode)
    pendingDelete.value = null
  } catch (err) {
    deleteError.value = (err as Error)?.message || 'Couldn’t delete that link'
    pendingDelete.value = null
  } finally {
    deleting.value = false
  }
}

async function signIn() {
  signingIn.value = true
  signInError.value = ''
  try {
    await signInWithBrowser('sign-in')
    if (visible.value) await session.recheck()
  } catch (err) {
    signInError.value = (err as Error)?.message || 'Sign-in didn’t finish. Try again.'
  } finally {
    signingIn.value = false
  }
}

function openSettingsSection(section: string) {
  dialog.close()
  window.dispatchEvent(new CustomEvent('open-settings', { detail: section }))
}

onBeforeUnmount(() => {
  if (copiedTimer) clearTimeout(copiedTimer)
  session.dispose()
})
</script>
