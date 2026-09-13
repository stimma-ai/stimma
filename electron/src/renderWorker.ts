/** Private, backend-owned worker. Uses the installed Electron, never app windows. */
import { app, BrowserWindow, session } from 'electron'
import readline from 'node:readline'
import ready from '../../backend/utils/render_ready.txt'

const ORIGIN = 'https://render.stimma.invalid'
const CSP = "default-src 'none'; img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; frame-src 'none'"
const MIME: Record<string, string> = {html:'text/html', css:'text/css', svg:'image/svg+xml', png:'image/png', jpg:'image/jpeg', jpeg:'image/jpeg', webp:'image/webp', gif:'image/gif', woff:'font/woff', woff2:'font/woff2', ttf:'font/ttf', otf:'font/otf'}

type Job = {html: string; assets: Record<string,string>; width:number; height:number|null; dpr:number}
app.setPath('userData', process.env.STIMMA_RENDER_PROFILE!)
app.disableHardwareAcceleration()
app.commandLine.appendSwitch('disable-background-timer-throttling')
app.on('window-all-closed', () => {})
let current: BrowserWindow | undefined
async function render(job: Job) {
  const partition = 'local-render-worker'
  const isolated = session.fromPartition(partition, {cache:false})
  const missing = new Set<string>()
  const win = current = new BrowserWindow({show:false, width:job.width, height:job.height || 1, transparent:true,
    webPreferences:{session:isolated, offscreen:true, sandbox:true, contextIsolation:true, nodeIntegration:false, backgroundThrottling:false}})
  isolated.setPermissionRequestHandler((_wc, _permission, callback) => callback(false))
  isolated.webRequest.onBeforeRequest((details, callback) => {
    const allowed = details.url === 'about:blank' || details.url.startsWith(`${ORIGIN}/`) || details.url.startsWith('data:')
    if (!allowed) missing.add('External resource blocked')
    callback({cancel:!allowed})
  })
  isolated.protocol.handle('https', request => {
    const url = new URL(request.url)
    const name = decodeURIComponent(url.pathname.slice(1))
    if (url.origin !== ORIGIN) return new Response('', {status:403})
    const body = name === 'index.html' ? Buffer.from(job.html) : job.assets[name] ? Buffer.from(job.assets[name], 'base64') : null
    if (!body) { missing.add(name); return new Response('', {status:404}) }
    return new Response(body, {headers:{'Content-Type':MIME[name.split('.').pop()!] || 'application/octet-stream', 'Content-Security-Policy':CSP}})
  })
  win.webContents.setWindowOpenHandler(() => ({action:'deny'}))
  try {
    await win.loadURL(`${ORIGIN}/index.html`)
    const debug = win.webContents.debugger
    debug.attach('1.3')
    const metrics = (height:number) => debug.sendCommand('Emulation.setDeviceMetricsOverride', {width:job.width,height,deviceScaleFactor:job.dpr,mobile:false})
    await metrics(job.height || 1)
    await debug.sendCommand('Emulation.setDefaultBackgroundColorOverride', {color:{r:0,g:0,b:0,a:0}})
    const measured = await win.webContents.executeJavaScript(ready)
    const height = job.height || Math.min(measured, job.width * 5)
    await metrics(height)
    await win.webContents.executeJavaScript(ready)
    if (missing.size) throw new Error(`Missing or blocked render resources: ${[...missing].join(', ')}`)
    const result = await debug.sendCommand('Page.captureScreenshot', {format:'png', clip:{x:0,y:0,width:job.width,height,scale:1}, captureBeyondViewport:true, fromSurface:true})
    return {png_b64:result.data, height}
  } finally {
    current = undefined
    win.destroy()
    isolated.protocol.unhandle('https')
    await isolated.clearStorageData()
  }
}
function stop() { current?.destroy(); app.exit(0) }
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
process.stdout.on('error', stop)
void app.whenReady().then(async () => {
  app.dock?.hide()
  const input = readline.createInterface({input:process.stdin, crlfDelay:Infinity})
  input.on('close', stop)
  for await (const line of input) {
    try { process.stdout.write(JSON.stringify(await render(JSON.parse(line))) + '\n') }
    catch (error) { process.stdout.write(JSON.stringify({error:String(error)}) + '\n') }
  }
  stop()
})
