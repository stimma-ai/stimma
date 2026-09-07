type Request = { method: string; args: Record<string, unknown> }
type AndroidPort = {
  postMessage(message: string): void
  onmessage: ((event: MessageEvent<string>) => void) | null
}
type NativeWindow = Window & {
  webkit?: { messageHandlers?: { stimma?: { postMessage(message: Request): Promise<unknown> } } }
  stimmaAndroid?: AndroidPort
}

let activePort: AndroidPort | undefined
let sequence = 0
const pending = new Map<number, { resolve(value: unknown): void; reject(error: Error): void; timer: ReturnType<typeof setTimeout> }>()

export function mobilePlatform(): 'ios' | 'android' | undefined {
  if (typeof window === 'undefined') return undefined
  const nativeWindow = window as NativeWindow
  if (typeof nativeWindow.stimmaAndroid?.postMessage === 'function') return 'android'
  if (typeof nativeWindow.webkit?.messageHandlers?.stimma?.postMessage === 'function') return 'ios'
  return undefined
}

export async function mobileNative<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
  const nativeWindow = window as NativeWindow
  const port = nativeWindow.stimmaAndroid
  if (!port) {
    const handler = nativeWindow.webkit?.messageHandlers?.stimma
    if (!handler) throw new Error('Open Stimma on your phone to connect to your Stimma Server.')
    return await handler.postMessage({ method, args }) as T
  }
  if (activePort !== port) {
    activePort = port
    port.onmessage = (event) => {
      let message: { id: number; result?: unknown; error?: string }
      try { message = JSON.parse(event.data) } catch { return }
      const request = pending.get(message.id)
      if (!request) return
      pending.delete(message.id)
      clearTimeout(request.timer)
      if (message.error) request.reject(new Error(message.error))
      else request.resolve(message.result)
    }
  }
  return await new Promise<T>((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => {
      pending.delete(id)
      reject(new Error('The mobile request timed out. Please try again.'))
    }, method === 'signIn' ? 310000 : method === 'share' ? 610000 : 120000)
    pending.set(id, { resolve: (value) => resolve(value as T), reject, timer })
    try { port.postMessage(JSON.stringify({ id, method, args })) }
    catch (error) { clearTimeout(timer); pending.delete(id); reject(error) }
  })
}
