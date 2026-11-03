import { computed, onScopeDispose, ref } from 'vue'
import { getReadDeadlineMs } from '../utils/readDeadline'

export interface SearchTask<T = any> {
  label: string
  read: (signal: AbortSignal) => Promise<T>
  apply: (result: T) => void
}

/** Independent search sections: each can finish, fail or retry on its own. */
export function useSearchTasks() {
  const pending = ref<string[]>([])
  const failed = ref<string[]>([])
  let generation = 0
  let controller: AbortController | null = null
  let tasks: SearchTask[] = []

  function cancel() {
    generation++
    controller?.abort()
    controller = null
    pending.value = []
    failed.value = []
  }

  async function execute(task: SearchTask, current: number, parent: AbortSignal) {
    const request = new AbortController()
    const abort = () => request.abort()
    parent.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(abort, getReadDeadlineMs())
    let rejectAborted: () => void = () => {}
    const aborted = new Promise<never>((_, reject) => {
      rejectAborted = () => reject(new Error('Search timed out or was cancelled'))
      request.signal.addEventListener('abort', rejectAborted, { once: true })
    })
    try {
      const result = await Promise.race([task.read(request.signal), aborted])
      if (current === generation) task.apply(result)
    } catch {
      if (current === generation && !parent.aborted) failed.value = [...failed.value, task.label]
    } finally {
      clearTimeout(timer)
      parent.removeEventListener('abort', abort)
      request.signal.removeEventListener('abort', rejectAborted)
      request.abort()
      if (current === generation) pending.value = pending.value.filter(label => label !== task.label)
    }
  }

  function run(next: SearchTask[]) {
    cancel()
    tasks = next
    controller = new AbortController()
    pending.value = next.map(task => task.label)
    return Promise.all(next.map(task => execute(task, generation, controller!.signal)))
  }

  function retry() {
    const retryTasks = tasks.filter(task => failed.value.includes(task.label))
    failed.value = []
    pending.value = [...pending.value, ...retryTasks.map(task => task.label)]
    if (!controller) return Promise.resolve([])
    return Promise.all(retryTasks.map(task => execute(task, generation, controller!.signal)))
  }

  onScopeDispose(cancel)
  return { loading: computed(() => pending.value.length > 0), pending, failed, run, retry, cancel }
}
