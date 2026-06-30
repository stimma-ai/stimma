/**
 * Server-side video frame grab.
 *
 * When a video lands in an image slot we turn it into a still *at that moment*
 * (the ingestion point), so it behaves exactly like an image from then on — prep,
 * paint, scale all apply to the still, and the still is what feeds the job. The
 * bundled ffmpeg does the extraction server-side, so it works for any codec
 * (WebKit can't decode some), never depends on the browser, and is testable.
 *
 * Source is either an OS file (a drop / file-picker) or a `sourcePath` pointing at
 * a library/reference video.
 */
import axios from 'axios'

export type FramePosition = 'first' | 'last' | 'middle' | 'custom'

export interface ExtractedFrame {
  path: string
  filename: string
  width: number
  height: number
  time: number       // timestamp (seconds) the frame was taken at
  duration: number   // source duration (seconds), 0 if unknown
  fps: number        // source frame rate, 0 if unknown
}

export interface ExtractFrameRequest {
  file?: File          // an OS file drop / picked file
  sourcePath?: string  // a library/reference video path
  position: FramePosition
  timeSeconds?: number // for position === 'custom'
}

export function useVideoFrameExtraction() {
  async function extractFrame(req: ExtractFrameRequest): Promise<ExtractedFrame> {
    const fd = new FormData()
    fd.append('position', req.position)
    if (req.timeSeconds != null) fd.append('time_seconds', String(req.timeSeconds))
    if (req.file) fd.append('file', req.file)
    if (req.sourcePath) fd.append('source_path', req.sourcePath)

    const { data } = await axios.post('/api/generate/extract-frame', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return {
      path: data.path,
      filename: data.filename,
      width: data.width,
      height: data.height,
      time: data.time_seconds,
      duration: data.duration,
      fps: data.fps ?? 0,
    }
  }

  return { extractFrame }
}
