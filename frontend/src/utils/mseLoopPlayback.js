const DEFAULT_INITIAL_LOOPS = 6
const DEFAULT_APPEND_LOOPS = 4
const DEFAULT_BUFFER_AHEAD_LOOPS = 3
const DEFAULT_RETAIN_BEHIND_LOOPS = 4

function waitForEvent(target, eventName) {
  return new Promise((resolve, reject) => {
    const onEvent = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(new Error(`MediaSource failed while waiting for ${eventName}`))
    }
    const cleanup = () => {
      target.removeEventListener(eventName, onEvent)
      target.removeEventListener('error', onError)
    }
    target.addEventListener(eventName, onEvent, { once: true })
    target.addEventListener('error', onError, { once: true })
  })
}

function appendBuffer(sourceBuffer, bytes) {
  return new Promise((resolve, reject) => {
    const onUpdateEnd = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(new Error('MSE SourceBuffer append failed'))
    }
    const cleanup = () => {
      sourceBuffer.removeEventListener('updateend', onUpdateEnd)
      sourceBuffer.removeEventListener('error', onError)
    }
    sourceBuffer.addEventListener('updateend', onUpdateEnd, { once: true })
    sourceBuffer.addEventListener('error', onError, { once: true })
    sourceBuffer.appendBuffer(bytes)
  })
}

function removeBuffer(sourceBuffer, start, end) {
  if (!(end > start)) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const onUpdateEnd = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(new Error('MSE SourceBuffer removal failed'))
    }
    const cleanup = () => {
      sourceBuffer.removeEventListener('updateend', onUpdateEnd)
      sourceBuffer.removeEventListener('error', onError)
    }
    sourceBuffer.addEventListener('updateend', onUpdateEnd, { once: true })
    sourceBuffer.addEventListener('error', onError, { once: true })
    sourceBuffer.remove(start, end)
  })
}

export class MseLoopPlayback {
  constructor(video, urls, options = {}) {
    this.video = video
    this.urls = urls
    this.onBoundary = options.onBoundary || null
    this.onReady = options.onReady || null
    this.onError = options.onError || null
    this.onMaintenanceError = options.onMaintenanceError || null
    // Align an object-fit: cover video with its face-cropped thumbnail. Only
    // correct for square containers; leave off for contain/full-frame players.
    // Also keeps the video invisible until a frame has actually been presented:
    // the compositor can paint the first frame before a just-set object-position
    // reaches the video layer, which reads as a one-frame position jump.
    this.applyFaceCrop = options.applyFaceCrop || false
    this.appliedObjectPosition = false
    this.hidOpacity = false
    this.initialLoops = options.initialLoops || DEFAULT_INITIAL_LOOPS
    this.appendLoops = options.appendLoops || DEFAULT_APPEND_LOOPS
    this.bufferAheadLoops = options.bufferAheadLoops || DEFAULT_BUFFER_AHEAD_LOOPS
    this.retainBehindLoops = options.retainBehindLoops || DEFAULT_RETAIN_BEHIND_LOOPS
    this.duration = 0
    this.destroyed = false
    this.appendedLoops = 0
    this.lastObservedLoop = 0
    this.objectUrl = null
    this.mediaSource = null
    this.sourceBuffer = null
    this.segmentBytes = null
    this.operation = Promise.resolve()
    this.raf = null
    this.maintenancePending = false
  }

  get logicalCurrentTime() {
    if (!(this.duration > 0)) return 0
    const value = this.video.currentTime % this.duration
    return value < 0 ? value + this.duration : value
  }

  seekLogical(seconds) {
    if (!(this.duration > 0)) return
    const max = Math.max(0, this.duration - 0.000_001)
    const logical = Math.min(max, Math.max(0, seconds))
    const loopStart = Math.floor(this.video.currentTime / this.duration) * this.duration
    this.video.currentTime = loopStart + logical
  }

  async start() {
    try {
      if (!('MediaSource' in window)) throw new Error('Media Source Extensions are unavailable')

      const manifestResponse = await fetch(this.urls.manifest)
      if (!manifestResponse.ok) throw new Error(`MSE preparation failed (${manifestResponse.status})`)
      const manifest = await manifestResponse.json()
      if (this.destroyed) return
      if (!MediaSource.isTypeSupported(manifest.mime_type)) {
        throw new Error(`MSE codec is unsupported: ${manifest.mime_type}`)
      }

      this.duration = Number(manifest.duration)
      if (!(this.duration > 0)) throw new Error('MSE manifest has no valid duration')

      if (this.applyFaceCrop && manifest.face_object_position) {
        const { x, y } = manifest.face_object_position
        this.video.style.objectPosition = `${x}% ${y}%`
        this.appliedObjectPosition = true
      }
      if (this.applyFaceCrop) {
        // Opacity (not display) so decode and frame presentation still run;
        // the matching thumbnail stays visible underneath until we reveal.
        this.video.style.opacity = '0'
        this.hidOpacity = true
      }

      const [initResponse, segmentResponse] = await Promise.all([
        fetch(this.urls.init),
        fetch(this.urls.segment),
      ])
      if (!initResponse.ok || !segmentResponse.ok) throw new Error('MSE media segment fetch failed')
      const [initBytes, segmentBytes] = await Promise.all([
        initResponse.arrayBuffer(),
        segmentResponse.arrayBuffer(),
      ])
      if (this.destroyed) return
      this.segmentBytes = segmentBytes

      this.mediaSource = new MediaSource()
      this.objectUrl = URL.createObjectURL(this.mediaSource)
      this.video.src = this.objectUrl
      await waitForEvent(this.mediaSource, 'sourceopen')
      if (this.destroyed) return

      this.sourceBuffer = this.mediaSource.addSourceBuffer(manifest.mime_type)
      this.sourceBuffer.mode = 'sequence'
      await appendBuffer(this.sourceBuffer, initBytes)
      await this._appendLoopBatch(this.initialLoops)
      if (this.destroyed) return

      this.lastObservedLoop = Math.floor(this.video.currentTime / this.duration)
      this._tick()
      this.onReady?.(this)
      if (this.hidOpacity) this._revealOnFirstFrame()
      await this.video.play().catch(() => {})
    } catch (error) {
      if (!this.destroyed) this.onError?.(error)
      if (!this.destroyed) throw error
    }
  }

  _revealOnFirstFrame() {
    const reveal = () => {
      if (this.destroyed || !this.hidOpacity) return
      this.video.style.opacity = ''
      this.hidOpacity = false
    }
    if (typeof this.video.requestVideoFrameCallback === 'function') {
      this.video.requestVideoFrameCallback(() => reveal())
      // Backstop in case frame callbacks are throttled — the thumbnail
      // matches the video framing, so a late reveal is invisible anyway.
      setTimeout(reveal, 500)
    } else if (this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      reveal()
    } else {
      this.video.addEventListener('loadeddata', reveal, { once: true })
    }
  }

  async _appendLoopBatch(count) {
    for (let index = 0; index < count; index += 1) {
      if (this.destroyed) return
      // Give WebKit a fresh backing store for each repeated fragment so every
      // append is parsed as an independent sequence group.
      await appendBuffer(this.sourceBuffer, this.segmentBytes.slice(0))
      this.appendedLoops += 1
    }
  }

  _queueMaintenance() {
    if (this.maintenancePending || this.destroyed || !this.sourceBuffer) return
    this.maintenancePending = true
    this.operation = this.operation.then(async () => {
      if (this.destroyed) return
      const bufferedEnd = this.sourceBuffer.buffered.length
        ? this.sourceBuffer.buffered.end(this.sourceBuffer.buffered.length - 1)
        : 0
      if (bufferedEnd - this.video.currentTime < this.duration * this.bufferAheadLoops) {
        await this._appendLoopBatch(this.appendLoops)
      }

      const currentLoop = Math.floor(this.video.currentTime / this.duration)
      const removeBefore = Math.max(0, (currentLoop - this.retainBehindLoops) * this.duration)
      if (removeBefore > 0 && this.sourceBuffer.buffered.length) {
        const bufferedStart = this.sourceBuffer.buffered.start(0)
        if (removeBefore > bufferedStart) {
          await removeBuffer(this.sourceBuffer, bufferedStart, removeBefore)
        }
      }
    }).catch((error) => {
      if (!this.destroyed) this.onMaintenanceError?.(error)
    }).finally(() => {
      this.maintenancePending = false
    })
  }

  _tick = () => {
    if (this.destroyed) return
    if (this.duration > 0) {
      const currentLoop = Math.floor(this.video.currentTime / this.duration)
      if (currentLoop > this.lastObservedLoop) {
        for (let loop = this.lastObservedLoop + 1; loop <= currentLoop; loop += 1) {
          this.onBoundary?.({ loop, playback: this })
        }
        this.lastObservedLoop = currentLoop
      } else if (currentLoop < this.lastObservedLoop) {
        this.lastObservedLoop = currentLoop
      }
      this._queueMaintenance()
    }
    this.raf = requestAnimationFrame(this._tick)
  }

  destroy() {
    if (this.destroyed) return
    this.destroyed = true
    if (this.raf != null) cancelAnimationFrame(this.raf)
    this.raf = null
    this.video.pause()

    try {
      if (this.sourceBuffer?.updating) this.sourceBuffer.abort()
      if (this.mediaSource?.readyState === 'open' && this.sourceBuffer) {
        this.mediaSource.removeSourceBuffer(this.sourceBuffer)
      }
    } catch { /* teardown is best-effort */ }

    // Recycled tiles reuse the same <video> element for other items — clear
    // any per-item framing or reveal state we applied.
    if (this.appliedObjectPosition) {
      this.video.style.objectPosition = ''
      this.appliedObjectPosition = false
    }
    if (this.hidOpacity) {
      this.video.style.opacity = ''
      this.hidOpacity = false
    }

    this.video.removeAttribute('src')
    this.video.load()
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl)
    this.objectUrl = null
    this.sourceBuffer = null
    this.mediaSource = null
    this.segmentBytes = null
  }
}
