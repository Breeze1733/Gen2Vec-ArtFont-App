const { app, BrowserWindow, ipcMain, dialog, net, shell, Notification } = require('electron')
const path = require('path')
const fs = require('fs/promises')

const VECTORIZER_BACKEND_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_BACKEND_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'

function createWindow() {
  const win = new BrowserWindow({
    width: 1080,
    height: 760,
    minWidth: 920,
    minHeight: 640,
    title: '矢量艺术字生成器',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL)
    win.webContents.openDevTools({ mode: 'detach' })
    return
  }

  win.loadFile(path.join(__dirname, '../dist/index.html'))
}

function parseDataUrl(dataUrl) {
  const match = /^data:(.+?)(;base64)?,(.*)$/s.exec(dataUrl)
  if (!match) {
    return Buffer.from(dataUrl, 'utf8')
  }

  const isBase64 = !!match[2]
  const data = match[3]
  return isBase64 ? Buffer.from(data, 'base64') : Buffer.from(decodeURIComponent(data), 'utf8')
}

async function requestBackend(apiUrl, payload) {
  return new Promise((resolve, reject) => {
    try {
      const requestUrl = new URL(apiUrl)
      const request = net.request({
        method: 'POST',
        protocol: requestUrl.protocol,
        hostname: requestUrl.hostname,
        port: requestUrl.port,
        path: `${requestUrl.pathname}${requestUrl.search}`
      })

      request.setHeader('Content-Type', 'application/json')

      let body = ''
      request.on('response', (response) => {
        response.on('data', (chunk) => {
          body += chunk.toString()
        })
        response.on('end', () => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            try {
              resolve(JSON.parse(body))
            } catch (err) {
              reject(err)
            }
          } else {
            let detail = ''
            try {
              const parsed = JSON.parse(body)
              if (parsed && typeof parsed.detail === 'string') {
                detail = `: ${parsed.detail}`
              }
            } catch (err) {
              // Non-JSON body is still a valid backend error.
            }
            reject(new Error(`后端服务返回 ${response.statusCode}${detail}`))
          }
        })
      })

      request.on('error', reject)
      request.write(JSON.stringify(payload))
      request.end()
    } catch (err) {
      reject(err)
    }
  })
}

ipcMain.handle('art-text/get-app-version', async () => {
  return app.getVersion()
})

ipcMain.handle('art-text/is-dev', async () => {
  return !app.isPackaged || process.env.NODE_ENV !== 'production'
})

ipcMain.handle('art-text/notify', async (event, options) => {
  const { title = '通知', body = '', silent = false } = options || {}
  if (Notification.isSupported()) {
    new Notification({ title, body, silent }).show()
    return { ok: true }
  }
  throw new Error('系统通知不受支持。')
})

ipcMain.handle('art-text/open-external', async (event, url) => {
  if (!url || typeof url !== 'string') {
    throw new Error('Invalid URL')
  }
  await shell.openExternal(url)
  return { ok: true }
})

ipcMain.handle('art-text/vectorize', async (event, payload) => {
  return requestBackend(VECTORIZER_BACKEND_URL, payload)
})

ipcMain.handle('art-text/generate', async (event, payload) => {
  return requestBackend(TXT2IMG_BACKEND_URL, payload)
})

ipcMain.handle('art-text/save-file', async (event, options) => {
  const win = BrowserWindow.getFocusedWindow()
  const { data, defaultName = 'output', filters = [] } = options || {}
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: '保存文件',
    defaultPath: defaultName,
    filters
  })

  if (canceled || !filePath) {
    return { canceled: true }
  }

  const buffer = parseDataUrl(data)
  await fs.writeFile(filePath, buffer)
  return { canceled: false, filePath }
})

ipcMain.handle('art-text/save-results', async (event, options) => {
  const win = BrowserWindow.getFocusedWindow()
  const { results = {}, fileBase = 'art-text' } = options || {}
  const { canceled, filePaths } = await dialog.showOpenDialog(win, {
    title: '选择保存目录',
    properties: ['openDirectory', 'createDirectory']
  })

  if (canceled || !filePaths || filePaths.length === 0) {
    return { canceled: true }
  }

  const folder = filePaths[0]
  const savedFiles = []

  // 支持任意键的 results，按命名或内容推断文件类型
  for (const [key, data] of Object.entries(results || {})) {
    if (!data) continue

    let ext = 'bin'
    let buffer = null

    try {
      const str = String(data)
      const trimmed = str.trim()
      if (key === 'svg' || trimmed.startsWith('<svg')) {
        ext = 'svg'
        buffer = Buffer.from(str, 'utf8')
      } else if (key === 'metadata' || key.toLowerCase().includes('meta') || (trimmed.startsWith('{') || trimmed.startsWith('['))) {
        ext = 'json'
        buffer = Buffer.from(typeof data === 'string' ? data : JSON.stringify(data, null, 2), 'utf8')
      } else if (trimmed.startsWith('data:image/') || key.toLowerCase().includes('png') || key.toLowerCase().includes('image') || key.toLowerCase().includes('original') || key.toLowerCase().includes('preview') || key.toLowerCase().includes('transparent')) {
        ext = 'png'
        buffer = parseDataUrl(data)
      } else {
        // fallback: try to parse as data URL else write as utf8
        if (typeof data === 'string' && data.startsWith('data:')) {
          ext = 'bin'
          buffer = parseDataUrl(data)
        } else if (typeof data === 'string') {
          ext = 'txt'
          buffer = Buffer.from(data, 'utf8')
        } else {
          ext = 'bin'
          buffer = Buffer.from(JSON.stringify(data), 'utf8')
        }
      }
    } catch (err) {
      continue
    }

    const filePath = path.join(folder, `${fileBase}.${ext}`)
    await fs.writeFile(filePath, buffer)
    savedFiles.push(filePath)
  }

  return { canceled: false, filePaths: savedFiles }
})

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
