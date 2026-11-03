import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { getMedia, waitForShell } from '../helpers/app';

test('a three-minute video streams, scrubs, and loops in the slideshow', async ({ page }, testInfo) => {
  const source = testInfo.outputPath('long-video.mp4');
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i',
    'testsrc2=duration=180.4:size=128x128:rate=25', '-f', 'lavfi', '-i',
    'sine=duration=180.4:sample_rate=48000', '-c:v', 'libx264', '-preset', 'ultrafast',
    '-c:a', 'aac', '-shortest', source], { timeout: 30_000 });
  await page.goto('/browse');
  await waitForShell(page);
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const uploaded = await page.request.post('/api/generate/upload-bulk', {
    headers: { 'X-Profile-ID': profileId! },
    multipart: { files: { name: 'long-video.mp4', mimeType: 'video/mp4', buffer: await readFile(source) } },
  });
  expect(uploaded.ok()).toBe(true);
  const result = (await uploaded.json()).results[0];
  expect(result.status).toBe('success');
  let assetId: number | undefined;
  await expect.poll(async () => {
    assetId = (await getMedia(page, result.media_id)).asset_id;
    return assetId;
  }).toBeTruthy();
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.goto('/browse');
  await page.getByTestId(`media-grid-item-${assetId}`).click();
  const video = page.locator('video[data-gallery-picture]');
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate(v => (v as HTMLVideoElement).currentTime), { timeout: 15_000 }).toBeGreaterThan(0.1);
  expect(requests.some(url => url.includes('/playback/v1/small/segment-0.m4s'))).toBe(true);
  expect(requests.some(url => url.includes('/mse-loop/segment'))).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('streaming-slideshow.png') });
  const track = page.locator('img[src*="/generate/frame-strip"]').locator('..');
  await expect(track).toBeVisible();
  const box = await track.boundingBox();
  await track.click({ position: { x: box!.width * 0.995, y: box!.height / 2 } });
  await video.evaluate(v => { (v as HTMLVideoElement).playbackRate = 2; });
  await expect.poll(() => video.evaluate(v => (v as HTMLVideoElement).currentTime), { timeout: 15_000 }).toBeGreaterThan(180.4);
  expect(requests.some(url => url.includes('/segment-89.m4s'))).toBe(true);
  await page.getByTitle('Close slideshow', { exact: true }).click();
  await expect(video).toHaveCount(0);
});
