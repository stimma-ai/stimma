import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir, hostname } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'
import { build } from 'vite'
import { chromium, expect } from '@playwright/test'

const backend = fileURLToPath(new URL('../../backend', import.meta.url))
const scratch = mkdtempSync(join(tmpdir(), 'stimma-streaming-test-'))
const python = `
import hashlib, json, os, pathlib, subprocess
from utils import video_playback as v
p = pathlib.Path(os.environ['STIMMA_CACHE_DIR']) / 'source.mp4'
p.parent.mkdir(parents=True, exist_ok=True)
duration = os.environ.get('VIDEO_TEST_DURATION', '20.4')
fps = os.environ.get('VIDEO_TEST_FPS', '25')
rate = os.environ.get('VIDEO_TEST_SAMPLE_RATE', '48000')
subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'testsrc2=duration={duration}:size=1280x720:rate={fps}','-f','lavfi','-i',f'sine=duration={duration}:sample_rate={rate}','-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(p)],check=True,timeout=30)
h = hashlib.sha256(p.read_bytes()).hexdigest()
m = v.describe(p,h)
for r in m['renditions']: v._encode(p,v.cache_dir(h),m,r)
m['mime_type'] = v.mime_type((v.cache_dir(h)/'small'/'init.mp4').read_bytes(),True)
print(json.dumps({'root':str(v.cache_dir(h)),'manifest':m}))
`
let fixture, roundedFixture
try {
  fixture = JSON.parse(execFileSync('uv', ['run', '--no-sync', 'python', '-c', python], {
    cwd: backend, env: { ...process.env, STIMMA_CACHE_DIR: scratch }, encoding: 'utf8', timeout: 60_000,
  }))
  roundedFixture = JSON.parse(execFileSync('uv', ['run', '--no-sync', 'python', '-c', python], {
    cwd: backend, env: { ...process.env, STIMMA_CACHE_DIR: join(scratch, 'rounded'),
      VIDEO_TEST_DURATION: '16.375', VIDEO_TEST_FPS: '24', VIDEO_TEST_SAMPLE_RATE: '44100' },
    encoding: 'utf8', timeout: 60_000,
  }))
} catch (error) { rmSync(scratch, { recursive: true, force: true }); throw error }
const bundled = await build({
  configFile: false, logLevel: 'silent', build: { write: false, minify: false,
    lib: { entry: fileURLToPath(new URL('../src/utils/mseLoopPlayback.js', import.meta.url)), formats: ['iife'], name: 'PlaybackTest' },
  },
})
const script = (Array.isArray(bundled) ? bundled : [bundled]).flatMap(x => x.output).find(x => x.type === 'chunk').code
process.on('exit', () => rmSync(scratch, { recursive: true, force: true }))

async function open(t, { slow = false, managed = false, media = fixture } = {}) {
  const requests = []
  const server = createServer((req, res) => {
    const path = new URL(req.url, 'http://test.invalid').pathname
    if (path === '/playback') { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(media.manifest)); return }
    const part = path.match(/^\/playback\/v1\/(small|medium)\/(init.mp4|segment-\d+.m4s)$/)
    if (part) {
      requests.push({ variant: part[1], part: part[2] })
      res.setHeader('content-type', 'video/mp4')
      const bytes = readFileSync(join(media.root, part[1], part[2]))
      if (!slow) { res.end(bytes); return }
      let offset = 0
      const timer = setInterval(() => {
        if (offset >= bytes.length) { clearInterval(timer); res.end(); return }
        res.write(bytes.subarray(offset, offset + 2048)); offset += 2048
      }, 20) // ~0.8 Mbps, deliberately below the medium rendition's bitrate.
      res.on('close', () => clearInterval(timer))
      return
    }
    res.setHeader('content-type', 'text/html')
    res.end('<video playsinline style="width:100%;max-width:720px" id="video"></video>')
  })
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve))
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve) }))
  const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] })
  t.after(() => browser.close())
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  if (managed) await page.addInitScript(() => {
    window.ManagedMediaSource = class extends MediaSource {
      streaming = true
    }
  })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  t.after(() => assert.deepEqual(errors, []))
  await page.goto(`http://${hostname()}:${server.address().port}/`)
  await page.addScriptTag({ content: script })
  await page.evaluate(() => {
    window.failures = []; window.boundaries = []; window.frames = []
    const video = document.getElementById('video')
    video.muted = true
    const frame = (_, info) => {
      window.frames.push({ media: info.mediaTime, wall: performance.now() })
      video.requestVideoFrameCallback(frame)
    }
    video.requestVideoFrameCallback(frame)
    window.player = new PlaybackTest.MseLoopPlayback(video, { playback: '/playback', manifest: '/legacy' }, {
      onBoundary: event => window.boundaries.push(event.loop),
      onError: error => window.failures.push(error.message),
      onMaintenanceError: error => window.failures.push(error.message),
    })
    window.start = performance.now()
    void window.player.start().catch(error => window.failures.push(error.message))
  })
  return { page, requests }
}

test('slow mobile playback starts from a small segment without downloading the full video', { timeout: 30_000 }, async t => {
  const { page, requests } = await open(t, { slow: true })
  await expect.poll(() => page.evaluate(() => window.frames.length), { timeout: 12_000 }).toBeGreaterThan(0)
  const elapsed = await page.evaluate(() => window.frames[0].wall - window.start)
  t.diagnostic(`First frame at ${(elapsed / 1000).toFixed(2)} s on ~0.8 Mbps; ${requests.filter(x => x.part.startsWith('segment-')).length} segment requests`)
  assert.ok(elapsed < 5000, `first frame took ${elapsed} ms`)
  assert.ok(requests.filter(x => x.part.startsWith('segment-')).length < 4)
  assert.equal(requests[0].variant, 'small')
  await page.waitForTimeout(2500)
  assert.ok(await page.evaluate(() => video.currentTime) > 2)
  await page.evaluate(() => window.player.destroy())
  const count = requests.length
  await page.waitForTimeout(200)
  assert.equal(requests.length, count, 'destroy stops requesting video')
  assert.deepEqual(await page.evaluate(() => window.failures), [])
})

test('seeks into unfetched content and loops on one continuous timeline with bounded buffering', { timeout: 30_000 }, async t => {
  const { page, requests } = await open(t)
  await expect.poll(() => page.evaluate(() => window.frames.length)).toBeGreaterThan(3)
  await page.evaluate(() => { window.player.seekLogical(19.5); video.playbackRate = 2 })
  await expect.poll(() => page.evaluate(() => window.boundaries.length), { timeout: 8000 }).toBeGreaterThan(0)
  assert.ok(requests.some(x => x.part === 'segment-9.m4s'))
  assert.ok(requests.some(x => x.variant === 'medium'), 'fast connections upgrade quality')
  assert.ok(await page.evaluate(() => video.currentTime) > 20.4, 'loop never seeks the element back to zero')
  const stats = await page.evaluate(() => {
    const around = window.frames.filter(f => f.media > 20 && f.media < 21)
    return { count: around.length, gap: Math.max(0, ...around.slice(1).map((f, i) => f.wall - around[i].wall)),
      buffered: [...Array(video.buffered.length)].reduce((sum, _, i) => sum + video.buffered.end(i) - video.buffered.start(i), 0),
      cache: window.player.streamingPlayback.cacheBytes, failures: window.failures }
  })
  assert.ok(stats.count > 2)
  assert.ok(stats.gap < 250, `loop frame gap was ${stats.gap} ms`)
  assert.ok(stats.buffered < 18, `buffer grew to ${stats.buffered} seconds`)
  assert.ok(stats.cache <= 4 * 1024 * 1024)
  t.diagnostic(`Loop frame gap ${stats.gap.toFixed(0)} ms; ${stats.buffered.toFixed(1)} s buffered; ${(stats.cache / 1024 / 1024).toFixed(2)} MiB retained`)
  assert.deepEqual(stats.failures, [])
  await page.evaluate(() => window.player.destroy())
})

test('ManagedMediaSource obeys streaming demand and restores remote-playback policy on teardown', { timeout: 30_000 }, async t => {
  const { page, requests } = await open(t, { managed: true })
  await expect.poll(() => page.evaluate(() => window.frames.length)).toBeGreaterThan(0)
  assert.equal(await page.evaluate(() => video.disableRemotePlayback), true)
  await page.evaluate(() => {
    const source = window.player.streamingPlayback.source
    source.streaming = false
    source.dispatchEvent(new Event('endstreaming'))
    window.player.seekLogical(17)
  })
  await page.waitForTimeout(100)
  const stopped = requests.length
  await page.waitForTimeout(100)
  assert.equal(requests.length, stopped)
  await page.evaluate(() => {
    const source = window.player.streamingPlayback.source
    source.streaming = true
    source.dispatchEvent(new Event('startstreaming'))
  })
  await expect.poll(() => requests.length).toBeGreaterThan(stopped)
  await page.evaluate(() => window.player.destroy())
  assert.equal(await page.evaluate(() => video.disableRemotePlayback), false)
  assert.deepEqual(await page.evaluate(() => window.failures), [])
})

test('24 fps video with 44.1 kHz audio crosses rounded loop boundaries repeatedly', { timeout: 30_000 }, async t => {
  const { page } = await open(t, { media: roundedFixture })
  await expect.poll(() => page.evaluate(() => window.frames.length)).toBeGreaterThan(3)
  for (let loop = 1; loop <= 3; loop++) {
    await page.evaluate(atEnd => { window.player.seekLogical(window.player.duration - (atEnd ? 0 : 0.5)); video.playbackRate = 2 }, loop === 3)
    await expect.poll(() => page.evaluate(() => window.boundaries.length), { timeout: 6000 }).toBeGreaterThanOrEqual(loop)
  }
  assert.ok(await page.evaluate(() => video.currentTime > 3 * window.player.duration))
  assert.deepEqual(await page.evaluate(() => window.failures), [])
  await page.evaluate(() => window.player.destroy())
})
