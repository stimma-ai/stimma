// Test-only Electron app that writes localStorage into a Chromium userData
// directory. On Windows the caller points this at a WebView2-shaped
// `browser/EBWebView` root, producing the same LevelDB layout Tauri used.

const { app, BrowserWindow } = require('electron')
const { createServer } = require('node:http')
const path = require('node:path')

const [, , userDataDir, rowsBase64] = process.argv
if (!userDataDir || !rowsBase64) process.exit(2)

app.setPath('userData', path.resolve(userDataDir))

app.whenReady().then(async () => {
  const server = createServer((_req, res) => {
    res.setHeader('Content-Type', 'text/html')
    res.end('<!doctype html><title>storage fixture</title>')
  })
  await new Promise((resolve) => server.listen(48321, '127.0.0.1', resolve))

  const win = new BrowserWindow({ show: false })
  await win.loadURL('http://127.0.0.1:48321/')
  const rows = JSON.parse(Buffer.from(rowsBase64, 'base64').toString('utf8'))
  await win.webContents.executeJavaScript(`
    for (const [key, value] of ${JSON.stringify(rows)}) localStorage.setItem(key, value)
  `)
  await win.webContents.session.flushStorageData()
  win.destroy()
  server.close()
  app.quit()
}).catch((error) => {
  console.error(error)
  app.exit(1)
})
