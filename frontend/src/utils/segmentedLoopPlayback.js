import { appendBuffer, removeBuffer, mediaOperation } from './mseBuffers.js'

const BUFFER_AHEAD = 6
const RETAIN_BEHIND = 8
const CACHE_BYTES = 4 * 1024 * 1024
// Audio sample clocks and MP4 timescales can round an encoded endpoint a few
// microseconds short. Treat these as the canonical segment/loop boundary.
const TIMESTAMP_TOLERANCE = 0.001

export function playbackPartUrl(base, rendition, part) {
  const url = new URL(base, window.location.href)
  url.pathname += `/v1/${rendition}/${part}`
  return url.href
}

export class SegmentedLoopPlayback {
  constructor(owner, manifest) {
    this.owner = owner
    this.video = owner.video
    this.manifest = manifest
    this.duration = manifest.duration
    this.abort = new AbortController()
    this.request = null
    this.source = null
    this.buffer = null
    this.objectUrl = null
    this.destroyed = false
    this.pending = false
    this.seekEpoch = 0
    this.bandwidth = 0
    this.samples = 0
    this.variant = null
    this.cache = new Map()
    this.cacheBytes = 0
    this.lastLoop = 0
    this.failedRequests = 0
    this.retryAt = 0
    this.onSeek = () => { this.seekEpoch++; this.request?.abort(); this.queue() }
    this.onVisibility = () => { if (document.hidden) this.request?.abort(); else this.queue() }
  }

  url(variant, part) { return playbackPartUrl(this.owner.urls.playback, variant, part) }

  async start() {
    const Source = window.ManagedMediaSource || window.MediaSource
    if (!Source || !Source.isTypeSupported(this.manifest.mime_type)) {
      if (!this.video.canPlayType('application/vnd.apple.mpegurl')) throw new Error('Streaming video is unsupported')
      this.native = true
      this.onNativeEnd = () => {
        this.owner.onBoundary?.({ playback: this.owner })
        if (!this.destroyed) {
          this.video.currentTime = 0
          if (this.owner.shouldPlay()) void this.video.play().catch(() => {})
        }
      }
      this.video.addEventListener('ended', this.onNativeEnd)
      await mediaOperation(this.video, 'loadedmetadata', () => {
        this.video.src = this.url('auto', 'index.m3u8')
      }, this.abort.signal)
    } else {
      this.source = new Source()
      // iPhone MMS requires an AirPlay alternative or remote playback disabled.
      this.previousRemotePlayback = this.video.disableRemotePlayback
      if (window.ManagedMediaSource) this.video.disableRemotePlayback = true
      this.source.addEventListener('startstreaming', () => this.queue())
      this.source.addEventListener('endstreaming', () => this.request?.abort())
      this.objectUrl = URL.createObjectURL(this.source)
      await mediaOperation(this.source, 'sourceopen', () => { this.video.src = this.objectUrl }, this.abort.signal)
      this.source.duration = Infinity
      this.buffer = this.source.addSourceBuffer(this.manifest.mime_type)
      this.buffer.mode = 'segments'
      await this.appendAt(0)
      this.video.addEventListener('seeking', this.onSeek)
      document.addEventListener('visibilitychange', this.onVisibility)
      this.tick()
    }
    if (this.destroyed) return
    this.owner.onReady?.(this.owner)
    if (this.owner.hidOpacity) this.owner._revealOnFirstFrame()
    if (this.owner.shouldPlay()) await this.video.play().catch(() => {})
  }

  seekLogical(seconds) {
    const logical = Math.min(this.duration - 0.000001, Math.max(0, seconds))
    const loop = this.native ? 0 : Math.floor(this.video.currentTime / this.duration)
    this.video.currentTime = loop * this.duration + logical
  }

  async fetchPart(variant, name, epoch) {
    const url = this.url(variant.id, name)
    if (this.cache.has(url)) return this.cache.get(url).slice(0)
    const request = new AbortController()
    this.request = request
    const abort = () => request.abort()
    this.abort.signal.addEventListener('abort', abort, { once: true })
    // A bad high-quality request must not hold playback hostage. Retry from
    // the same timeline position at the smallest rendition after this budget.
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; abort() }, variant.id === this.manifest.renditions[0].id ? 30_000 : 4000)
    const started = performance.now()
    try {
      const response = await fetch(url, { signal: request.signal })
      if (!response.ok) throw new Error(`Video segment failed (${response.status})`)
      const bytes = await response.arrayBuffer()
      if (this.destroyed || epoch !== this.seekEpoch) throw new DOMException('Playback cancelled', 'AbortError')
      if (name !== 'init.mp4') {
        const measured = bytes.byteLength * 8000 / Math.max(1, performance.now() - started)
        this.bandwidth = this.bandwidth ? this.bandwidth * 0.6 + measured * 0.4 : measured
        this.samples++
      }
      if (bytes.byteLength <= CACHE_BYTES) {
        while (this.cache.size && this.cacheBytes + bytes.byteLength > CACHE_BYTES) {
          const first = this.cache.keys().next().value
          this.cacheBytes -= this.cache.get(first).byteLength
          this.cache.delete(first)
        }
        this.cache.set(url, bytes.slice(0))
        this.cacheBytes += bytes.byteLength
      }
      return bytes
    } catch (error) {
      if (timedOut && !this.destroyed && epoch === this.seekEpoch) throw new Error('Video segment timed out')
      throw error
    } finally {
      clearTimeout(timer)
      this.abort.signal.removeEventListener('abort', abort)
      if (this.request === request) this.request = null
    }
  }

  chooseVariant() {
    let selected = this.manifest.renditions[0]
    if (this.samples >= 2) {
      for (const variant of this.manifest.renditions) {
        if (variant.bandwidth * 1.7 < this.bandwidth) selected = variant
      }
    }
    return selected
  }

  async appendAt(time) {
    const epoch = this.seekEpoch
    const loop = Math.floor((time + 0.000000001) / this.duration)
    const logical = Math.max(0, time - loop * this.duration)
    const index = Math.min(this.manifest.segment_count - 1, Math.floor((logical + 0.000000001) / this.manifest.segment_duration))
    const variant = this.chooseVariant()
    const init = variant.id !== this.variant ? await this.fetchPart(variant, 'init.mp4', epoch) : null
    const bytes = await this.fetchPart(variant, `segment-${index}.m4s`, epoch)
    if (this.destroyed || epoch !== this.seekEpoch) return
    // Keep the original encoded A/V timestamps inside each repetition. Reset
    // only the loop offset; concatenating per-segment sequence groups drifts.
    this.buffer.timestampOffset = loop * this.duration
    if (init) {
      await appendBuffer(this.buffer, init, this.abort.signal)
      this.variant = variant.id
    }
    await appendBuffer(this.buffer, bytes, this.abort.signal)
    this.source.setLiveSeekableRange?.(0, (loop + 2) * this.duration)
  }

  bufferEnd(time) {
    const ranges = this.buffer.buffered
    for (let i = 0; i < ranges.length; i++) {
      const end = ranges.end(i)
      if (time >= ranges.start(i) - 0.05 && time <= end + TIMESTAMP_TOLERANCE) {
        const loopBoundary = Math.round(end / this.duration) * this.duration
        if (Math.abs(end - loopBoundary) <= TIMESTAMP_TOLERANCE) return loopBoundary
        const loopStart = Math.floor(end / this.duration) * this.duration
        const segmentBoundary = loopStart + Math.round((end - loopStart) / this.manifest.segment_duration) * this.manifest.segment_duration
        if (Math.abs(end - segmentBoundary) <= TIMESTAMP_TOLERANCE) return segmentBoundary
        return end
      }
    }
    return time
  }

  queue() {
    if (this.pending || this.destroyed || !this.buffer || document.hidden || performance.now() < this.retryAt) return
    if (window.ManagedMediaSource && !this.source.streaming) return
    this.pending = true
    void (async () => {
      const now = this.video.currentTime
      const before = Math.max(0, now - RETAIN_BEHIND)
      if (this.buffer.buffered.length && this.buffer.buffered.start(0) < before) {
        await removeBuffer(this.buffer, 0, before, this.abort.signal)
      }
      // A seek may leave a distant forward range. Evict it rather than growing
      // a second long-lived buffer each time the scrubber changes direction.
      const ranges = this.buffer.buffered
      if (ranges.length && ranges.end(ranges.length - 1) > now + BUFFER_AHEAD + this.manifest.segment_duration) {
        await removeBuffer(this.buffer, now + BUFFER_AHEAD + this.manifest.segment_duration, ranges.end(ranges.length - 1), this.abort.signal)
      }
      const end = this.bufferEnd(this.video.currentTime)
      if (end - this.video.currentTime < BUFFER_AHEAD) await this.appendAt(end)
      this.failedRequests = 0
    })().catch(error => {
      if (this.destroyed) return
      this.bandwidth = 0
      this.samples = 0
      // Seeks, mobile suspension, and MMS endstreaming intentionally abort.
      if (error.name === 'AbortError') return
      this.retryAt = performance.now() + 500
      this.failedRequests++
      if (this.failedRequests >= 3) this.owner.onError?.(error)
      else this.owner.onMaintenanceError?.(error)
    }).finally(() => { this.pending = false })
  }

  tick = () => {
    if (this.destroyed) return
    const loop = Math.floor(this.video.currentTime / this.duration)
    if (loop > this.lastLoop) this.owner.onBoundary?.({ loop, playback: this.owner })
    this.lastLoop = loop
    if (!this.destroyed) { this.queue(); this.raf = requestAnimationFrame(this.tick) }
  }

  destroy() {
    this.destroyed = true
    this.abort.abort()
    this.request?.abort()
    cancelAnimationFrame(this.raf)
    this.video.removeEventListener('seeking', this.onSeek)
    this.video.removeEventListener('ended', this.onNativeEnd)
    document.removeEventListener('visibilitychange', this.onVisibility)
    if (this.previousRemotePlayback !== undefined) this.video.disableRemotePlayback = this.previousRemotePlayback
    this.cache.clear()
    this.buffer = null
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl)
  }
}
