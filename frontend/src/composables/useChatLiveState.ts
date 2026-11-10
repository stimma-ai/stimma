/**
 * A chat's live sending state, owned once per chat rather than per view.
 *
 * The same chat can be mounted twice at once: full size (a KeepAlive'd route
 * view) and small in the dock. Both show one queue of messages waiting to be
 * sent and one "sending" flag, so moving between sizes never drops a queued
 * message. Only one view, the owner, drains the queue and steers: the most
 * recently shown live view of that chat. A view going out of sight steps to
 * the back of the line (so a chat nobody is looking at still drains, as it
 * always has); unmounting leaves it.
 */
import { computed, onUnmounted, ref, watch, type Ref } from 'vue'

export interface QueuedMessage {
  id: string
  text: string
  attachments: any[]
  mode: 'queue' | 'steer'
  steering: boolean
}

interface LiveState {
  queue: Ref<QueuedMessage[]>
  sending: Ref<boolean>
  /** Live views of this chat; the last one owns the queue. */
  holders: Ref<symbol[]>
}

const states = new Map<string, LiveState>()

// Chat ids are per database: `scope` names the profile and database, so the
// same id in another profile is another chat's state.
function stateFor(chatId: number | string | null, scope: string): LiveState {
  const key = `${scope}/${chatId == null ? '' : String(chatId)}`
  let state = states.get(key)
  if (!state) {
    state = { queue: ref<QueuedMessage[]>([]), sending: ref(false), holders: ref<symbol[]>([]) }
    states.set(key, state)
  }
  return state
}

export function useChatLiveState(chatId: Ref<number | string | null>, scope: () => string = () => '') {
  const token = Symbol('chat-view')
  const current = computed(() => stateFor(chatId.value, scope()))

  const messageQueue = computed<QueuedMessage[]>({
    get: () => current.value.queue.value,
    set: (v) => { current.value.queue.value = v },
  })
  const sending = computed<boolean>({
    get: () => current.value.sending.value,
    set: (v) => { current.value.sending.value = v },
  })

  function without(state: LiveState) {
    return state.holders.value.filter(t => t !== token)
  }
  /** This view is the one in sight: it owns the chat's queue. */
  function claim() {
    const state = current.value
    state.holders.value = [...without(state), token]
  }
  /** Out of sight but still alive: a fallback owner. */
  function stepBack() {
    const state = current.value
    state.holders.value = [token, ...without(state)]
  }
  function release(state = current.value) {
    state.holders.value = without(state)
  }
  /** Another live view still holds this chat (its queue stays with it). */
  function heldElsewhere(id: number | string | null) {
    return stateFor(id, scope()).holders.value.some(t => t !== token)
  }

  const isOwner = computed(() => {
    const holders = current.value.holders.value
    return holders.length > 0 && holders[holders.length - 1] === token
  })

  // Switching conversations moves this view's hold with it.
  watch(chatId, (_next, prev) => {
    const prevState = stateFor(prev ?? null, scope())
    const held = prevState.holders.value.includes(token)
    release(prevState)
    if (held) claim()
  })
  onUnmounted(() => release())

  return { messageQueue, sending, isOwner, claim, stepBack, release, heldElsewhere }
}

/** Test hook. */
export function _resetChatLiveStateForTests() {
  states.clear()
}
