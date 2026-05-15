const { app, BrowserWindow, ipcMain, dialog, net } = require('electron')
const path = require('path')
const fs = require('fs/promises')

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000/api/v1/generate'

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

ipcMain.handle('art-text/generate', async (event, payload) => {
  const apiUrl = process.env.ART_TEXT_BACKEND_URL || DEFAULT_BACKEND_URL
  return requestBackend(apiUrl, payload)
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
