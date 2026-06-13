const { app, BrowserWindow, ipcMain, dialog, net, shell, Notification } = require('electron')
const path = require('path')
const fs = require('fs/promises')
const fsSync = require('fs')
const { spawn, spawnSync } = require('child_process')
const netModule = require('net')

// ── 模块级状态 ──
let splashWin = null
let mainWin = null
let txt2imgProc = null
let vectorizerProc = null
let engineDownloadProc = null
let modelDownloadProc = null
let startupState = { ready: false, modelsReady: false, backendsRunning: false, modelsSkipped: false, engineSkipped: false }
let startupError = null

// 强制 Windows 使用高性能独立显卡（NVIDIA/AMD），避免默认分配集显导致 WebGL 检测不到独显
// 必须在 app.whenReady() 之前调用
// 注：部分 Electron 版本下 commandLine 可能未就绪，包裹 try/catch 作为尽力而为的优化
try {
  if (app && app.commandLine) {
    app.commandLine.appendSwitch('force_high_performance_gpu')
  }
} catch (_) {
  // 非关键路径，静默忽略
}

const VECTORIZER_BACKEND_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_BACKEND_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'

function deriveShutdownUrl(apiUrl) {
  try {
    const u = new URL(apiUrl)
    u.pathname = '/shutdown'
    return u.toString()
  } catch {
    return null
  }
}

const SHUTDOWN_URLS = [
  deriveShutdownUrl(TXT2IMG_BACKEND_URL),
  deriveShutdownUrl(VECTORIZER_BACKEND_URL),
].filter(Boolean)

// ── 后端路径解析 ──

function getBackendDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend')
  }
  // 开发模式：不自动管理后端，由开发者手动启动
  return null
}

function getAcceptanceScriptCandidates() {
  const candidates = []

  if (app.isPackaged) {
    const installDir = path.dirname(process.execPath)
    candidates.push(path.join(installDir, 'tests', 'run-acceptance.bat'))
    candidates.push(path.join(process.resourcesPath, '..', 'tests', 'run-acceptance.bat'))
    candidates.push(path.join(process.resourcesPath, 'tests', 'run-acceptance.bat'))
  }

  candidates.push(path.resolve(__dirname, '..', '..', '..', 'tests', 'run-acceptance.bat'))
  candidates.push(path.resolve(process.cwd(), 'tests', 'run-acceptance.bat'))
  candidates.push(path.resolve(process.cwd(), '..', '..', 'tests', 'run-acceptance.bat'))

  return [...new Set(candidates)]
}

function resolveAcceptanceScriptPath() {
  for (const candidate of getAcceptanceScriptCandidates()) {
    if (fsSync.existsSync(candidate)) {
      return candidate
    }
  }
  throw new Error('未找到 run-acceptance.bat。请确认安装目录下存在 tests\\run-acceptance.bat。')
}

// ── 端口检测 ──

function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = netModule.createServer()
    server.once('error', () => resolve(true))
    server.once('listening', () => {
      server.close()
      resolve(false)
    })
    server.listen(port, '127.0.0.1')
  })
}

// ── ComfyUI 引擎管理 ──

function getComfyUIPortableDir(backendDir) {
  return path.join(backendDir, 'ComfyUI_windows_portable_nvidia', 'ComfyUI_windows_portable')
}

function isComfyUIReady(backendDir) {
  if (!backendDir) return true // 开发模式跳过
  const sentinel = path.join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'main.py')
  return fsSync.existsSync(sentinel)
}

function getEngineDownloadTrackPath(backendDir, taskName) {
  const taskPaths = {
    '7za.exe': path.join(backendDir, '7za920.zip'),
    'ComfyUI_portable': path.join(backendDir, 'ComfyUI_windows_portable_nvidia.7z'),
    'ComfyUI_windows_portable_nvidia.7z': path.join(backendDir, 'ComfyUI_windows_portable_nvidia.7z'),
    'ComfyUI-GGUF': path.join(backendDir, 'ComfyUI-GGUF.zip'),
    'ComfyUI-GGUF.zip': path.join(backendDir, 'ComfyUI-GGUF.zip'),
    'ComfyUI-Inspyrenet-Rembg': path.join(backendDir, 'ComfyUI-Inspyrenet-Rembg.zip'),
    'ComfyUI-Inspyrenet-Rembg.zip': path.join(backendDir, 'ComfyUI-Inspyrenet-Rembg.zip'),
  }
  return taskPaths[taskName] || null
}

function downloadComfyUIEngine(backendDir, onProgress) {
  return new Promise((resolve, reject) => {
    const ps1Path = path.join(backendDir, 'download-comfyui-engine.ps1')
    if (!fsSync.existsSync(ps1Path)) {
      reject(new Error(`未找到引擎下载脚本: ${ps1Path}`))
      return
    }

    if (onProgress) {
      onProgress({ step: 1, phase: 'downloading', message: '正在准备下载推理引擎...', percent: -1, fileIndex: 0, totalFiles: 0 })
    }

    const proc = spawn('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-File', ps1Path,
      '-Electron',
      '-DestDir', backendDir
    ], {
      cwd: backendDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    engineDownloadProc = proc

    let totalFiles = 0
    let completedFiles = 0
    let failedFiles = 0
    let currentFileName = ''
    let currentFileSize = ''
    let finalResult = null
    let stdoutBuffer = ''
    // 文件大小轮询跟踪（与模型下载一致）
    let trackedFiles = []
    let startedDownloading = false

    const handleEngineOutputLines = (lines) => {
      for (const line of lines) {
        if (!line.startsWith('ENGINEDL:')) continue
        const parts = line.substring(9).split('|')
        const type = parts[0]

        switch (type) {
          case 'TOTAL':
            totalFiles = parseInt(parts[1], 10) || 0
            break
          case 'START':
            currentFileName = parts[1] || ''
            currentFileSize = parts[2] || ''
            startedDownloading = true
            // 添加到文件大小跟踪列表
            const engineFilePath = getEngineDownloadTrackPath(backendDir, currentFileName)
            if (engineFilePath) {
              let initialSize = 0
              try { if (fsSync.existsSync(engineFilePath)) initialSize = fsSync.statSync(engineFilePath).size } catch (_) {}
              trackedFiles.push({
                name: currentFileName,
                fullPath: engineFilePath,
                lastSize: initialSize,
                lastTime: Date.now(),
                remoteSize: 0
              })
            }
            if (onProgress) {
              onProgress({
                step: 1, phase: 'downloading',
                message: `正在下载 (${completedFiles + 1}/${totalFiles || '?'}) ${currentFileName}`,
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles + 1,
                totalFiles,
                fileName: currentFileName,
                fileSize: currentFileSize
              })
            }
            break
          case 'DONE':
          case 'SKIP':
            completedFiles++
            const doneName = parts[1] || currentFileName
            trackedFiles = trackedFiles.filter(f => f.name !== doneName)
            if (onProgress) {
              onProgress({
                step: 1, phase: 'downloading',
                message: type === 'SKIP' ? `跳过: ${doneName}` : `完成: ${doneName}`,
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles,
                totalFiles,
                fileName: doneName,
                speed: '',
                eta: '',
                filePercent: -1
              })
            }
            break
          case 'ERROR':
            completedFiles++
            failedFiles++
            const errName = parts[1] || currentFileName
            if (onProgress) {
              onProgress({
                step: 1, phase: 'downloading',
                message: `下载失败: ${errName}`,
                detail: parts[2] ? `错误: ${parts.slice(2).join(':')}` : '',
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles,
                totalFiles,
                fileName: errName
              })
            }
            break
          case 'COMPLETE':
            const ok = parseInt(parts[1], 10) || 0
            const skip = parseInt(parts[2], 10) || 0
            const fail = parseInt(parts[3], 10) || 0
            finalResult = { ok, skip, fail }
            if (onProgress) {
              onProgress({
                step: 1,
                phase: fail > 0 ? 'error' : 'complete',
                message: fail > 0 ? `引擎下载失败 (${fail} 个组件失败)` : '推理引擎就绪',
                percent: fail > 0 ? 0 : 100,
                fileIndex: totalFiles || completedFiles,
                totalFiles: totalFiles || completedFiles,
                result: finalResult
              })
            }
            break
          case 'READY':
            break
        }
      }
    }

    proc.stdout.on('data', (chunk) => {
      stdoutBuffer += chunk.toString()
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() || ''
      handleEngineOutputLines(lines.filter(Boolean))
    })

    // 每 2 秒轮询文件大小，推算速度/ETA/百分比
    const progressInterval = setInterval(() => {
      if (trackedFiles.length === 0) return

      let totalSpeed = ''
      let totalEta = ''
      let maxFilePct = -1

      for (const tf of trackedFiles) {
        try {
          if (fsSync.existsSync(tf.fullPath)) {
            const currentSize = fsSync.statSync(tf.fullPath).size
            const now = Date.now()
            const elapsedSecs = (now - tf.lastTime) / 1000

            if (elapsedSecs >= 1.5 && currentSize > tf.lastSize) {
              const bytesPerSec = (currentSize - tf.lastSize) / elapsedSecs
              if (tf.remoteSize <= 0) {
                const sizeStr = currentFileSize || ''
                if (sizeStr.includes('GB')) {
                  tf.remoteSize = parseFloat(sizeStr) * 1024 * 1024 * 1024
                } else if (sizeStr.includes('MB')) {
                  tf.remoteSize = parseFloat(sizeStr) * 1024 * 1024
                } else if (sizeStr.includes('KB')) {
                  tf.remoteSize = parseFloat(sizeStr) * 1024
                }
              }

              const speedMBs = bytesPerSec / (1024 * 1024)
              if (speedMBs >= 0.01) {
                totalSpeed = `${speedMBs.toFixed(1)} MB/s`
                if (tf.remoteSize > 0 && currentSize > 0) {
                  const remaining = tf.remoteSize - currentSize
                  if (remaining > 0 && bytesPerSec > 0) {
                    const etaSec = Math.round(remaining / bytesPerSec)
                    if (etaSec >= 3600) {
                      totalEta = `${Math.floor(etaSec / 3600)}h${Math.floor((etaSec % 3600) / 60)}m`
                    } else if (etaSec >= 60) {
                      totalEta = `${Math.floor(etaSec / 60)}m${etaSec % 60}s`
                    } else {
                      totalEta = `${etaSec}s`
                    }
                  }
                }
                if (tf.remoteSize > 0) {
                  maxFilePct = Math.min(100, Math.round((currentSize / tf.remoteSize) * 100))
                }
              }
              tf.lastSize = currentSize
              tf.lastTime = now
            } else if (tf.lastSize === 0 && currentSize > 0) {
              tf.lastSize = currentSize
              tf.lastTime = now
            }
          }
        } catch (_) { /* 文件可能被锁定，跳过 */ }
      }

      if (startedDownloading && onProgress) {
        onProgress({
          step: 1, phase: 'downloading',
          message: `正在下载 (${completedFiles + 1}/${totalFiles || '?'}) ${currentFileName}`,
          percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
          fileIndex: completedFiles + 1,
          totalFiles,
          fileName: currentFileName,
          fileSize: currentFileSize,
          speed: totalSpeed,
          eta: totalEta,
          filePercent: maxFilePct
        })
      }
    }, 2000)

    proc.stderr.on('data', (chunk) => {
      console.warn('[download-comfyui-engine stderr]', chunk.toString())
    })

    proc.on('error', (err) => {
      clearInterval(progressInterval)
      if (engineDownloadProc === proc) engineDownloadProc = null
      reject(new Error(`启动引擎下载脚本失败: ${err.message}`))
    })

    proc.on('close', (code) => {
      clearInterval(progressInterval)
      if (engineDownloadProc === proc) engineDownloadProc = null
      if (stdoutBuffer.trim()) {
        handleEngineOutputLines([stdoutBuffer.trim()])
        stdoutBuffer = ''
      }
      if (code !== 0 && failedFiles === 0) {
        reject(new Error(`引擎下载脚本异常退出 (退出码: ${code})`))
        return
      }
      const result = finalResult || {
        ok: code === 0 && failedFiles === 0 && totalFiles > 0 ? totalFiles : completedFiles - failedFiles,
        skip: 0,
        fail: failedFiles
      }
      if (!finalResult && code === 0 && failedFiles === 0 && onProgress) {
        onProgress({
          step: 1,
          phase: 'complete',
          message: '推理引擎就绪',
          percent: 100,
          fileIndex: totalFiles || completedFiles,
          totalFiles: totalFiles || completedFiles,
          result
        })
      }
      if (failedFiles > 0 && onProgress && !finalResult) {
        onProgress({
          step: 1,
          phase: 'error',
          message: `引擎下载失败 (${failedFiles} 个组件失败)`,
          percent: 0,
          fileIndex: completedFiles,
          totalFiles: totalFiles || completedFiles
        })
      }
      // 验证 sentinel + GGUF
      if (!isComfyUIReady(backendDir)) {
        reject(new Error('引擎下载后未找到 ComfyUI/main.py'))
        return
      }
      // 验证 GGUF 也存在
      const ggufSentinel = path.join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'custom_nodes', 'ComfyUI-GGUF', 'nodes.py')
      if (!fsSync.existsSync(ggufSentinel)) {
        reject(new Error('引擎下载后未找到 ComfyUI-GGUF custom node'))
        return
      }
      const inspyrenetDir = path.join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'custom_nodes', 'ComfyUI-Inspyrenet-Rembg')
      const inspyrenetReady = fsSync.existsSync(inspyrenetDir) && fsSync
        .readdirSync(inspyrenetDir, { withFileTypes: true })
        .some((entry) => entry.isFile() && entry.name.endsWith('.py'))
      if (!inspyrenetReady) {
        reject(new Error('引擎下载后未找到 ComfyUI-Inspyrenet-Rembg custom node'))
        return
      }
      resolve(result)
    })
  })
}

// ── 模型管理 ──

function getComfyUIModelsDir(backendDir) {
  return path.join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'models')
}

const REQUIRED_MODEL_FILES = [
  ['diffusion_models', 'z_image_turbo_bf16.safetensors', 10 * 1024 ** 3, '12.3 GB'],
  ['unet', 'flux1-schnell-fp8-e4m3fn.safetensors', 10 * 1024 ** 3, '11.9 GB'],
  ['text_encoders', 'qwen_2.5_vl_7b_fp8_scaled.safetensors', 8 * 1024 ** 3, '9.4 GB'],
  ['diffusion_models', 'qwen-image-2512-Q3_K_M.gguf', 7 * 1024 ** 3, '9 GB'],
  ['text_encoders', 'qwen_3_4b.safetensors', 6 * 1024 ** 3, '8.0 GB'],
  ['clip', 't5xxl_fp8_e4m3fn.safetensors', 4 * 1024 ** 3, '4.9 GB'],
  ['loras', 'Qwen-Image-Lightning-4steps-V1.0.safetensors', 1 * 1024 ** 3, '1.7 GB'],
  ['vae', 'ae.safetensors', 200 * 1024 ** 2, '335 MB'],
  ['vae', 'qwen_image_vae.safetensors', 150 * 1024 ** 2, '254 MB'],
  ['clip', 'clip_l.safetensors', 100 * 1024 ** 2, '246 MB'],
  ['inspyrenet/.transparent-background', 'ckpt_base.pth', 150 * 1024 ** 2, '170 MB'],
]

function getRequiredModelPaths(backendDir) {
  const modelsDir = getComfyUIModelsDir(backendDir)
  return REQUIRED_MODEL_FILES.map(([subdir, filename, minBytes, sizeLabel]) => {
    const filePath = path.join(modelsDir, subdir, filename)
    return { subdir, filename, filePath, completePath: `${filePath}.complete`, minBytes, sizeLabel }
  })
}

async function getMissingModels(backendDir) {
  if (!backendDir) return []
  const missing = []
  for (const model of getRequiredModelPaths(backendDir)) {
    try {
      const stat = await fs.stat(model.filePath)
      if (!stat.isFile() || stat.size < model.minBytes) missing.push(model)
    } catch {
      missing.push(model)
    }
  }
  return missing
}

async function checkModelsExist(backendDir) {
  if (!backendDir) return true // 开发模式跳过
  return (await getMissingModels(backendDir)).length === 0
}

function downloadModels(backendDir, onProgress) {
  return new Promise((resolve, reject) => {
    const ps1Path = path.join(backendDir, 'download-models.ps1')
    if (!fsSync.existsSync(ps1Path)) {
      if (onProgress) {
        onProgress({ step: 2, phase: 'error', message: '未找到模型下载脚本，请重新安装应用', percent: 0 })
      }
      reject(new Error(`未找到模型下载脚本: ${ps1Path}`))
      return
    }

    if (onProgress) {
      onProgress({ step: 2, phase: 'downloading', message: '正在准备下载...', percent: -1, fileIndex: 0, totalFiles: 0 })
    }

    const proc = spawn('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-File', ps1Path,
      '-Electron'
    ], {
      cwd: backendDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    modelDownloadProc = proc

    let totalFiles = 0
    let completedFiles = 0
    let failedFiles = 0
    let currentFileName = ''
    let currentFileSize = ''
    let currentSubdir = ''
    let finalResult = null

    // 已开始下载的模型文件跟踪（用于轮询子进度）
    let trackedFiles = [] // [{ name, subdir, fullPath, lastSize, lastTime, remoteSize }]
    let startedDownloading = false
    let stdoutBuffer = ''

    const handleDownloadOutputLines = (lines) => {
      for (const line of lines) {
        if (!line.startsWith('MODELDL:')) continue
        const parts = line.substring(8).split('|')
        const type = parts[0]

        switch (type) {
          case 'TOTAL':
            totalFiles = parseInt(parts[1], 10) || 0
            break
          case 'START':
            currentFileName = parts[1] || ''
            currentSubdir = parts[2] || ''
            currentFileSize = parts[3] || ''
            startedDownloading = true
            // 添加到跟踪列表
            if (currentFileName && currentSubdir) {
              const modelsDir = getComfyUIModelsDir(backendDir)
              const fullPath = path.join(modelsDir, currentSubdir, currentFileName)
              let initialSize = 0
              try { if (fsSync.existsSync(fullPath)) initialSize = fsSync.statSync(fullPath).size } catch (_) {}
              trackedFiles.push({
                name: currentFileName,
                subdir: currentSubdir,
                fullPath,
                lastSize: initialSize,
                lastTime: Date.now(),
                remoteSize: 0
              })
            }
            if (onProgress) {
              onProgress({
                step: 2, phase: 'downloading',
                message: `正在下载 (${completedFiles + 1}/${totalFiles || '?'}) ${currentFileName}`,
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles + 1,
                totalFiles,
                fileName: currentFileName,
                fileSize: currentFileSize
              })
            }
            break
          case 'DONE':
          case 'SKIP':
            completedFiles++
            // 从跟踪列表中移除
            const doneName = parts[1] || currentFileName
            trackedFiles = trackedFiles.filter(f => f.name !== doneName)
            if (onProgress) {
              onProgress({
                step: 2, phase: 'downloading',
                message: type === 'SKIP' ? `跳过: ${doneName}` : `完成: ${doneName}`,
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles,
                totalFiles,
                fileName: doneName,
                speed: '',
                eta: '',
                filePercent: -1
              })
            }
            break
          case 'ERROR':
            completedFiles++
            failedFiles++
            const errName = parts[1] || currentFileName
            trackedFiles = trackedFiles.filter(f => f.name !== errName)
            if (onProgress) {
              onProgress({
                step: 2, phase: 'downloading',
                message: `下载失败: ${errName}`,
                detail: parts[4] ? `错误: ${parts.slice(4).join(':')}` : '',
                percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
                fileIndex: completedFiles,
                totalFiles,
                fileName: errName,
                errorCode: parts[3] || '0'
              })
            }
            break
          case 'COMPLETE':
            trackedFiles = []
            const ok = parseInt(parts[1], 10) || 0
            const skip = parseInt(parts[2], 10) || 0
            const fail = parseInt(parts[3], 10) || 0
            finalResult = { ok, skip, fail }
            if (onProgress) {
              onProgress({
                step: 2, phase: 'complete',
                message: fail > 0 ? `模型下载完成 (${ok} 成功, ${fail} 失败)` : '模型下载完成',
                percent: 100,
                fileIndex: totalFiles || completedFiles,
                totalFiles: totalFiles || completedFiles,
                speed: '',
                eta: '',
                filePercent: -1,
                result: finalResult
              })
            }
            break
          case 'CHECK':
          case 'RESUME':
            // 这些只是信息提示，不触发进度推送
            break
          case 'READY':
          case 'ENGINE_OK':
            break
        }
      }
    }

    proc.stdout.on('data', (chunk) => {
      stdoutBuffer += chunk.toString()
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() || ''
      handleDownloadOutputLines(lines.filter(Boolean))
    })

    // 每 2 秒轮询文件大小，推算速度/ETA/百分比
    const progressInterval = setInterval(() => {
      if (trackedFiles.length === 0) return

      const modelsDir = getComfyUIModelsDir(backendDir)
      let totalSpeed = ''
      let totalEta = ''
      let maxFilePct = -1

      for (const tf of trackedFiles) {
        try {
          if (fsSync.existsSync(tf.fullPath)) {
            const currentSize = fsSync.statSync(tf.fullPath).size
            const now = Date.now()
            const elapsedSecs = (now - tf.lastTime) / 1000

            if (elapsedSecs >= 1.5 && currentSize > tf.lastSize) {
              const bytesPerSec = (currentSize - tf.lastSize) / elapsedSecs
              // 尝试获取远程总大小
              if (tf.remoteSize <= 0) {
                const sizeStr = currentFileSize || ''
                if (sizeStr.includes('GB')) {
                  tf.remoteSize = parseFloat(sizeStr) * 1024 * 1024 * 1024
                } else if (sizeStr.includes('MB')) {
                  tf.remoteSize = parseFloat(sizeStr) * 1024 * 1024
                }
              }

              const speedMBs = bytesPerSec / (1024 * 1024)
              if (speedMBs >= 0.01) {
                totalSpeed = `${speedMBs.toFixed(1)} MB/s`
                // ETA
                if (tf.remoteSize > 0 && currentSize > 0) {
                  const remaining = tf.remoteSize - currentSize
                  if (remaining > 0 && bytesPerSec > 0) {
                    const etaSec = Math.round(remaining / bytesPerSec)
                    if (etaSec >= 3600) {
                      totalEta = `${Math.floor(etaSec / 3600)}h${Math.floor((etaSec % 3600) / 60)}m`
                    } else if (etaSec >= 60) {
                      totalEta = `${Math.floor(etaSec / 60)}m${etaSec % 60}s`
                    } else {
                      totalEta = `${etaSec}s`
                    }
                  }
                }
                // 文件内百分比
                if (tf.remoteSize > 0) {
                  maxFilePct = Math.min(100, Math.round((currentSize / tf.remoteSize) * 100))
                }
              }
              tf.lastSize = currentSize
              tf.lastTime = now
            } else if (tf.lastSize === 0 && currentSize > 0) {
              tf.lastSize = currentSize
              tf.lastTime = now
            }
          }
        } catch (_) { /* 文件可能被锁定，跳过 */ }
      }

      if (startedDownloading && onProgress) {
        onProgress({
          step: 2, phase: 'downloading',
          message: `正在下载 (${completedFiles + 1}/${totalFiles || '?'}) ${currentFileName}`,
          percent: totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : -1,
          fileIndex: completedFiles + 1,
          totalFiles,
          fileName: currentFileName,
          fileSize: currentFileSize,
          speed: totalSpeed,
          eta: totalEta,
          filePercent: maxFilePct,
          subdir: currentSubdir
        })
      }
    }, 2000)

    proc.stderr.on('data', (chunk) => {
      console.warn('[download-models stderr]', chunk.toString())
    })

    proc.on('error', (err) => {
      clearInterval(progressInterval)
      if (modelDownloadProc === proc) modelDownloadProc = null
      reject(new Error(`启动下载脚本失败: ${err.message}`))
    })

    proc.on('close', (code) => {
      clearInterval(progressInterval)
      if (modelDownloadProc === proc) modelDownloadProc = null
      if (stdoutBuffer.trim()) {
        handleDownloadOutputLines([stdoutBuffer.trim()])
        stdoutBuffer = ''
      }
      if (code !== 0 && failedFiles === 0 && !finalResult) {
        // 脚本自身退出非零但无具体文件错误
        reject(new Error(`模型下载脚本异常退出 (退出码: ${code})`))
        return
      }
      const result = finalResult || {
        ok: code === 0 && failedFiles === 0 && totalFiles > 0 ? totalFiles : completedFiles - failedFiles,
        skip: 0,
        fail: failedFiles
      }
      if (!finalResult && code === 0 && failedFiles === 0 && onProgress) {
        onProgress({
          step: 2,
          phase: 'complete',
          message: '模型下载完成',
          percent: 100,
          fileIndex: totalFiles || completedFiles,
          totalFiles: totalFiles || completedFiles,
          speed: '',
          eta: '',
          filePercent: -1,
          result
        })
      }
      resolve(result)
    })
  })
}

// ── 后端进程生命周期 ──

function spawnBackend(exePath, cwd) {
  if (!fsSync.existsSync(exePath)) {
    throw new Error(`未找到后端程序: ${exePath}`)
  }

  const proc = spawn(exePath, [], {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })

  proc.on('error', (err) => {
    console.error(`[backend] ${path.basename(exePath)} 进程错误:`, err.message)
  })

  return proc
}

function killProcessTree(proc) {
  if (!proc || proc.killed || !proc.pid) return
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill.exe', ['/PID', String(proc.pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true,
      })
    } else {
      proc.kill('SIGTERM')
    }
  } catch (_) {
    try { proc.kill() } catch {}
  }
}

async function waitForHealthz(url, timeoutMs = 30000, onProgress) {
  const deadline = Date.now() + timeoutMs
  let lastError = null

  while (Date.now() < deadline) {
    try {
      const elapsed = timeoutMs - (deadline - Date.now())
      const percent = Math.min(99, Math.round((elapsed / timeoutMs) * 100))

      const resp = await fetch(url, { signal: AbortSignal.timeout(3000) })
      if (resp.ok) {
        const body = await resp.json().catch(() => ({}))
        if (onProgress) {
          onProgress({ phase: 'waiting', message: `${body.service || '服务'} 已就绪`, percent: 100 })
        }
        return { ready: true, service: body.service || 'unknown' }
      }
    } catch (err) {
      lastError = err
      if (onProgress) {
        const elapsed = timeoutMs - (deadline - Date.now())
        const percent = Math.min(99, Math.round((elapsed / timeoutMs) * 100))
        onProgress({ phase: 'waiting', message: '等待服务就绪...', percent })
      }
    }
    await new Promise(r => setTimeout(r, 1000))
  }

  return { ready: false, error: lastError?.message || '服务启动超时' }
}

async function checkBackendHealth(port, expectedService) {
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/healthz`, { signal: AbortSignal.timeout(2000) })
    if (resp.ok) {
      const body = await resp.json().catch(() => ({}))
      if (body.service === expectedService) {
        return { running: true, matches: true, service: body.service }
      }
      return { running: true, matches: false, service: body.service || 'unknown' }
    }
  } catch { /* 端口无响应 */ }
  return { running: false, matches: false, service: null }
}

async function startBackends(backendDir, onProgress) {
  if (!backendDir) {
    // 开发模式：不做任何事
    if (onProgress) {
      onProgress({ step: 3, phase: 'done', message: '开发模式，后端由开发者手动管理', percent: 100 })
    }
    return { txt2imgReady: true, vectorizerReady: true }
  }

  // ── 矢量化后端 (端口 8000) ──
  if (onProgress) {
    onProgress({ step: 3, phase: 'starting_vectorizer', message: '正在启动矢量化服务...', percent: 10 })
  }

  const vecExe = path.join(backendDir, 'vectorizer-backend.exe')

  // 检查端口是否已被占用
  const vecHealth = await checkBackendHealth(8000, 'vectorizer-api')
  if (vecHealth.running && vecHealth.matches) {
    if (onProgress) {
      onProgress({ step: 3, phase: 'waiting_vectorizer', message: '矢量化服务已在运行，复用现有进程', percent: 50 })
    }
  } else if (vecHealth.running && !vecHealth.matches) {
    throw new Error('端口 8000 已被其他程序占用，请关闭后重试')
  } else {
    try {
      vectorizerProc = spawnBackend(vecExe, backendDir)
      const vecResult = await waitForHealthz('http://127.0.0.1:8000/healthz', 30000, (p) => {
        if (onProgress) {
          onProgress({ step: 3, phase: 'waiting_vectorizer', message: p.message, percent: 20 + Math.round(p.percent * 0.3) })
        }
      })
      if (!vecResult.ready) {
        throw new Error(`矢量化服务启动超时: ${vecResult.error}`)
      }
    } catch (err) {
      throw new Error(`矢量化服务启动失败: ${err.message}`)
    }
  }

  if (onProgress) {
    onProgress({ step: 3, phase: 'starting_txt2img', message: '正在启动文生图服务...', percent: 55 })
  }

  // ── 文生图后端 (端口 9001) ──
  const txt2imgExe = path.join(backendDir, 'txt2img-backend.exe')

  // 检查端口是否已被占用
  const t2iHealth = await checkBackendHealth(9001, 'txt2img-api')
  if (t2iHealth.running && t2iHealth.matches) {
    if (onProgress) {
      onProgress({ step: 3, phase: 'waiting_txt2img', message: '文生图服务已在运行，复用现有进程', percent: 85 })
    }
  } else if (t2iHealth.running && !t2iHealth.matches) {
    throw new Error('端口 9001 已被其他程序占用，请关闭后重试')
  } else {
    try {
      txt2imgProc = spawnBackend(txt2imgExe, backendDir)
      const t2iResult = await waitForHealthz('http://127.0.0.1:9001/healthz', 30000, (p) => {
        if (onProgress) {
          onProgress({ step: 3, phase: 'waiting_txt2img', message: p.message, percent: 55 + Math.round(p.percent * 0.4) })
        }
      })
      if (!t2iResult.ready) {
        throw new Error(`文生图服务启动超时: ${t2iResult.error}`)
      }
    } catch (err) {
      throw new Error(`文生图服务启动失败: ${err.message}`)
    }
  }

  if (onProgress) {
    onProgress({ step: 3, phase: 'done', message: '所有服务已就绪', percent: 100 })
  }

  startupState.backendsRunning = true
  return { txt2imgReady: true, vectorizerReady: true }
}

// ── 启动编排 ──

async function runStartupSequence(splashWin) {
  const backendDir = getBackendDir()

  // 向 splash 发送进度
  const sendProgress = (data) => {
    if (splashWin && !splashWin.isDestroyed()) {
      splashWin.webContents.send('splash:progress', data)
    }
  }

  try {
    // ── 步骤 1: 检查 / 下载 ComfyUI 引擎 ──
    currentStartupStep = 1
    sendProgress({ step: 1, phase: 'checking', message: '正在检查推理引擎...', percent: -1 })

    if (backendDir) {
      const enginePs1 = path.join(backendDir, 'download-comfyui-engine.ps1')
      if (!fsSync.existsSync(enginePs1)) {
        sendProgress({ step: 1, phase: 'done', message: '未包含引擎下载脚本，使用本地降级引擎', percent: 100 })
        startupState.engineSkipped = true
      } else if (!isComfyUIReady(backendDir)) {
        sendProgress({
          step: 1, phase: 'prompt',
          message: '需要下载并配置推理引擎ComfyUI',
          percent: 0,
          promptLabel: '跳过',
          promptConfirm: '开始下载',
          promptDetail: '下载后即可使用 GPU 推理生成艺术字'
        })

        const action = await waitForSplashAction()
        if (action === 'download') {
          await downloadComfyUIEngine(backendDir, sendProgress)
          startupState.engineSkipped = false
        } else {
          sendProgress({ step: 1, phase: 'done', message: '已跳过引擎下载，文生图使用本地降级引擎', percent: 100 })
          startupState.engineSkipped = true
        }
      } else {
        sendProgress({ step: 1, phase: 'done', message: '推理引擎就绪', percent: 100 })
      }
    } else {
      sendProgress({ step: 1, phase: 'done', message: '推理引擎就绪 (开发模式)', percent: 100 })
    }

    // ── 步骤 2: 检查 / 下载模型 ──
    currentStartupStep = 2
    sendProgress({ step: 2, phase: 'checking', message: '正在检查 AI 模型...', percent: -1 })

    if (startupState.engineSkipped) {
      sendProgress({ step: 2, phase: 'done', message: '引擎未安装，跳过模型检查', percent: 100 })
      startupState.modelsSkipped = true
    } else {
      const missingModels = backendDir ? await getMissingModels(backendDir) : []
      if (missingModels.length > 0 && backendDir) {
        const ps1Path = path.join(backendDir, 'download-models.ps1')
        if (!fsSync.existsSync(ps1Path)) {
          sendProgress({ step: 2, phase: 'done', message: '未包含模型下载脚本，使用本地降级引擎', percent: 100 })
          startupState.modelsSkipped = true
        } else {
          sendProgress({
            step: 2, phase: 'prompt',
            message: '需要下载本地 AI 模型',
            percent: 0,
            promptLabel: '跳过',
            promptConfirm: '开始下载',
            promptDetail: '下载脚本会自动跳过已存在的模型'
          })

          const action = await waitForSplashAction()
          if (action === 'download') {
            const result = await downloadModels(backendDir, sendProgress)
            startupState.modelsReady = result.fail === 0
            startupState.modelsSkipped = false
          } else {
            sendProgress({ step: 2, phase: 'done', message: '已跳过模型下载，文生图使用本地降级引擎', percent: 100 })
            startupState.modelsSkipped = true
            startupState.modelsReady = false
          }
        }
      } else {
        sendProgress({ step: 2, phase: 'done', message: 'AI 模型就绪', percent: 100 })
        startupState.modelsReady = true
      }
    }

    // ── 步骤 3: 启动后端服务 ──
    currentStartupStep = 3
    sendProgress({ step: 3, phase: 'starting', message: '正在启动后端服务...', percent: -1 })

    await startBackends(backendDir, sendProgress)

    // ── 步骤 4: 完成 ──
    sendProgress({ step: 4, phase: 'complete', message: '正在启动应用...', percent: 100 })
    startupState.ready = true

    return { success: true }

  } catch (err) {
    startupError = err.message
    sendProgress({
      step: currentStartupStep,
      phase: 'error',
      message: err.message,
      percent: 0
    })
    return { success: false, error: err.message }
  }
}

// 当前启动步骤（错误时使用）
let currentStartupStep = 1

// 等待 splash 窗口中用户的操作
const EventEmitter = require('events')
class SplashActionEmitter extends EventEmitter {}
const splashActions = new SplashActionEmitter()
const SPLASH_ACTION_EVENT = 'splash-action'

function waitForSplashAction() {
  return new Promise((resolve) => {
    splashActions.once(SPLASH_ACTION_EVENT, (action) => {
      resolve(action)
    })
  })
}

ipcMain.on('splash:action', (_event, data) => {
  // data 可以是 { action: 'xxx' } 对象或 'xxx' 字符串（preload 传的是对象）
  let action
  if (typeof data === 'string') {
    action = data
  } else if (data && typeof data === 'object') {
    action = data.action
  }

  if (action) {
    if (action === 'minimize-window') {
      const win = BrowserWindow.fromWebContents(_event.sender)
      if (win && !win.isDestroyed()) win.minimize()
      return
    }

    // Generic download/skip/retry actions go to waitForSplashAction
    if (action === 'exit-app') {
      forceQuit()
    } else {
      splashActions.emit(SPLASH_ACTION_EVENT, action)
    }
  }
})

// ── 窗口管理 ──

function createSplashWindow() {
  const win = new BrowserWindow({
    width: 520,
    height: 580,
    resizable: false,
    frame: false,
    alwaysOnTop: true,
    center: true,
    show: false,
    backgroundColor: '#f7f3ea',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  win.loadFile(path.join(__dirname, 'splash.html'))

  win.once('ready-to-show', () => {
    win.show()
  })

  return win
}

function createMainWindow() {
  const win = new BrowserWindow({
    width: 1080,
    height: 760,
    minWidth: 920,
    minHeight: 640,
    title: '矢量艺术字生成器',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  // 窗口准备好后最大化显示
  win.once('ready-to-show', () => {
    win.maximize()
    win.show()
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL)
    win.webContents.openDevTools({ mode: 'detach' })
    return win
  }

  win.loadFile(path.join(__dirname, '../dist/index.html'))
  return win
}

function showMainWindow() {
  mainWin = createMainWindow()
  mainWin.on('closed', () => {
    mainWin = null
  })
  return mainWin
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

function getOutputRoot() {
  if (process.env.ART_TEXT_OUTPUT_ROOT) {
    return path.resolve(process.env.ART_TEXT_OUTPUT_ROOT)
  }

  const appPath = app.getAppPath()
  // 开发模式下 appPath 通常是 apps/desktop，按项目根目录输出到 outputs/
  // 打包后 resources/app.asar 上一级是 resources/，再上一级是安装目录
  // 统一回到项目根目录或安装目录
  if (!app.isPackaged && path.basename(appPath) === 'desktop') {
    return path.resolve(appPath, '..', '..', 'outputs')
  }

  // 打包后：安装目录下的 outputs/（与 gen2vec_cli.exe 同级）
  const installDir = path.dirname(process.execPath)
  return path.resolve(installDir, 'outputs')
}

function padTaskIndex(index) {
  const safeIndex = Number.isFinite(Number(index)) && Number(index) > 0 ? Number(index) : 1
  return String(Math.trunc(safeIndex)).padStart(3, '0')
}

function transliterateChinese(text) {
  const map = {
    爱: 'ai', 情: 'qing', 海: 'hai', 梨: 'li', 园: 'yuan', 醉: 'zui', 梦: 'meng', 七: 'qi', 里: 'li', 香: 'xiang',
    红: 'hong', 豆: 'dou', 抹: 'mo', 茶: 'cha', 青: 'qing', 山: 'shan', 集: 'ji', 夏: 'xia', 日: 'ri', 冰: 'bing', 饮: 'yin',
    花: 'hua', 朝: 'chao', 节: 'jie', 咖: 'ka', 啡: 'fei', 字: 'zi', 艺: 'yi', 术: 'shu', 文: 'wen', 本: 'ben', 图: 'tu'
  }
  return Array.from(String(text || '')).map((char) => {
    if (map[char]) return map[char]
    return /[\u3400-\u9fff]/u.test(char) ? `u${char.codePointAt(0).toString(16)}` : char
  }).join('-')
}

function safeTaskSlug(text) {
  const transliterated = transliterateChinese(text || 'art-text')
  const slug = transliterated
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
  return (slug || 'art-text').slice(0, 48)
}

function buildTaskDirectoryName({ startedAt = null, mode = 'single', index = 1, text = 'art-text', seed = 0 } = {}) {
  const taskId = mode === 'batch' ? `${formatTaskStartedAt(startedAt)}_${padTaskIndex(index)}` : formatTaskStartedAt(startedAt)
  return `task_${taskId}_${safeTaskSlug(text)}_seed-${seed || 0}`
}

function formatTaskStartedAt(startedAt) {
  const date = startedAt ? new Date(startedAt) : new Date()
  const validDate = Number.isNaN(date.getTime()) ? new Date() : date
  const pad = (value, width = 2) => String(value).padStart(width, '0')
  return [
    validDate.getFullYear(),
    pad(validDate.getMonth() + 1),
    pad(validDate.getDate()),
    '_',
    pad(validDate.getHours()),
    pad(validDate.getMinutes()),
    pad(validDate.getSeconds()),
    '_',
    pad(validDate.getMilliseconds(), 3)
  ].join('')
}

async function ensureUniqueTaskDir({ outputRoot, mode = 'single', index = 1, text = 'art-text', seed = 0, startedAt = null, summaryDir = null }) {
  const root = path.resolve(outputRoot || getOutputRoot())
  await fs.mkdir(root, { recursive: true })

  const baseName = buildTaskDirectoryName({ startedAt, mode, index, text, seed })
  let taskName = baseName
  let taskDir = path.join(root, taskName)
  let counter = 2
  while (fsSync.existsSync(taskDir)) {
    taskName = `${baseName}_${counter}`
    taskDir = path.join(root, taskName)
    counter += 1
  }

  await fs.mkdir(taskDir, { recursive: true })
  return buildTaskInfo({ outputRoot: root, taskDir, taskName, mode, index, seed, summaryDir })
}

function buildTaskInfo({ outputRoot, taskDir, taskName, mode, index, seed, summaryDir }) {
  const summaryRoot = summaryDir || (mode === 'batch-batch' ? taskDir : outputRoot)
  const paths = {
    original: path.join(taskDir, 'original.png'),
    transparent: path.join(taskDir, 'transparent.png'),
    svg: path.join(taskDir, 'result.svg'),
    preview: path.join(taskDir, 'preview.png'),
    metadata: path.join(taskDir, 'metadata.json'),
    log: path.join(taskDir, 'run.log'),
    workflows: path.join(taskDir, 'workflows'),
    workflowApi: path.join(taskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: path.join(taskDir, 'workflows', 'nodes.md'),
    modelDependencies: path.join(taskDir, 'workflows', 'model_dependencies.json'),
    summary: path.join(summaryRoot, 'batch_summary.csv'),
    summaryDir: summaryRoot
  }
  return { outputRoot, taskDir, taskName, mode, index, seed, paths }
}

function bufferForArtifact(data, isText = false) {
  if (data === undefined || data === null || data === '') return null
  if (Buffer.isBuffer(data)) return data
  if (typeof data === 'object') return Buffer.from(JSON.stringify(data, null, 2), 'utf8')
  const str = String(data)
  if (!isText && str.startsWith('data:')) return parseDataUrl(str)
  return Buffer.from(str, 'utf8')
}

async function writeArtifactFile(filePath, data, isText = false) {
  const buffer = bufferForArtifact(data, isText)
  if (!buffer) return null
  await fs.mkdir(path.dirname(filePath), { recursive: true })
  await fs.writeFile(filePath, buffer)
  return filePath
}

function csvEscape(value) {
  const text = value === undefined || value === null ? '' : String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

function extractQualityMetrics(metadata = {}) {
  const generationMs = metadata?.generation?.duration_ms
  const vectorMs = metadata?.stats?.elapsed_ms
  const normalizedGenerationMs = generationMs === undefined || generationMs === null ? '' : generationMs
  const normalizedVectorMs = vectorMs === undefined || vectorMs === null ? '' : vectorMs
  const pngTransparency = metadata?.preprocess?.png_transparency
  const svgFidelity = metadata?.quality?.svg_fidelity
  return {
    generation_ms: normalizedGenerationMs,
    vector_ms: normalizedVectorMs,
    png_transparency: pngTransparency === undefined || pngTransparency === null ? '' : pngTransparency,
    svg_fidelity: svgFidelity === undefined || svgFidelity === null ? '' : svgFidelity
  }
}

function appendQualityMetricsToRunLog(runLog = '', metadata = {}) {
  if (!runLog) return runLog
  const metrics = extractQualityMetrics(metadata)
  const upsertMetric = (text, key, value) => {
    const line = `${key}=${value}`
    const pattern = new RegExp(`(^|\\n)${key}=.*(?=\\n|$)`)
    if (pattern.test(text)) {
      return text.replace(pattern, (match, prefix) => `${prefix}${line}`)
    }
    return `${text}\n${line}`
  }
  return [
    ['generation_ms', metrics.generation_ms],
    ['vector_ms', metrics.vector_ms],
    ['png_transparency', metrics.png_transparency],
    ['svg_fidelity', metrics.svg_fidelity]
  ].reduce((text, [key, value]) => upsertMetric(text, key, value), runLog)
}

async function appendBatchSummaryCsv(summaryPath, row = {}) {
  const columns = [
    'task_id', 'task_name', 'mode', 'status', 'text', 'prompt', 'seed', 'resolution', 'task_dir',
    'run_log_path',
    'generation_ms', 'vector_ms', 'png_transparency', 'svg_fidelity', 'error'
  ]
  await fs.mkdir(path.dirname(summaryPath), { recursive: true })
  const exists = fsSync.existsSync(summaryPath)
  const line = columns.map((key) => csvEscape(row[key])).join(',')
  const content = `${exists ? '' : `${columns.join(',')}\n`}${line}\n`
  await fs.appendFile(summaryPath, content, 'utf8')
}

function inferLegacyExt(key, data) {
  const lowerKey = String(key).toLowerCase()
  const str = typeof data === 'string' ? data.trim() : ''
  if (lowerKey === 'svg' || lowerKey.includes('svg') || str.startsWith('<svg')) return 'svg'
  if (lowerKey === 'metadata' || lowerKey.includes('meta') || str.startsWith('{') || str.startsWith('[')) return 'json'
  if (lowerKey.includes('log')) return 'log'
  if (str.startsWith('data:image/') || ['original', 'transparent', 'preview', 'png'].some(k => lowerKey.includes(k))) return 'png'
  if (typeof data === 'string') return 'txt'
  return 'bin'
}

function buildWorkflowArtifacts({ metadata = {}, taskName = '', seed = 0, mode = 'single', workflowApi = null, modelDependencies = null }) {
  if (workflowApi || modelDependencies) {
    return {
      workflowApi: workflowApi || {
        task_name: taskName,
        mode,
        seed,
        workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
        prompt: metadata?.generation?.prompt || metadata?.prompt || '',
        text: metadata?.generation?.text || '',
        resolution: metadata?.generation?.resolution || '',
        captured_at: new Date().toISOString()
      },
      workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为桌面端运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
      modelDependencies: modelDependencies || {
        engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
        workflow: metadata?.workflow || metadata?.generation?.workflow || null,
        style: metadata?.style || metadata?.generation?.style || null,
        note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。'
      }
    }
  }
  return {
    workflowApi: {
      task_name: taskName,
      mode,
      seed,
      workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
      prompt: metadata?.generation?.prompt || metadata?.prompt || '',
      text: metadata?.generation?.text || '',
      resolution: metadata?.generation?.resolution || '',
      captured_at: new Date().toISOString()
    },
    workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为桌面端运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
    modelDependencies: {
      engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
      workflow: metadata?.workflow || metadata?.generation?.workflow || null,
      style: metadata?.style || metadata?.generation?.style || null,
      note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。'
    }
  }
}

async function requestBackend(apiUrl, payload) {
  return new Promise((resolve, reject) => {
    let request = null
    let settled = false
    let timer = null

    const finish = (fn, value) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      fn(value)
    }

    try {
      const requestUrl = new URL(apiUrl)
      const { __timeoutMs = 300000, ...backendPayload } = payload || {}
      request = net.request({
        method: 'POST',
        protocol: requestUrl.protocol,
        hostname: requestUrl.hostname,
        port: requestUrl.port,
        path: `${requestUrl.pathname}${requestUrl.search}`
      })

      timer = setTimeout(() => {
        try { request?.abort() } catch {}
        finish(reject, new Error(`后端请求超时（${Math.round(Number(__timeoutMs) / 1000)} 秒）`))
      }, Number(__timeoutMs) || 300000)

      request.setHeader('Content-Type', 'application/json')

      let body = ''
      request.on('response', (response) => {
        response.on('data', (chunk) => {
          body += chunk.toString()
        })
        response.on('end', () => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            try {
              finish(resolve, JSON.parse(body))
            } catch (err) {
              finish(reject, err)
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
            finish(reject, new Error(`后端服务返回 ${response.statusCode}${detail}`))
          }
        })
      })

      request.on('error', (err) => finish(reject, err))
      request.write(JSON.stringify(backendPayload))
      request.end()
    } catch (err) {
      try { request?.abort() } catch {}
      finish(reject, err)
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

ipcMain.handle('art-text/open-path', async (event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') {
    throw new Error('Invalid path')
  }
  const errorMessage = await shell.openPath(targetPath)
  if (errorMessage) {
    throw new Error(errorMessage)
  }
  return { ok: true }
})

ipcMain.handle('art-text/launch-acceptance-test', async () => {
  if (process.platform !== 'win32') {
    throw new Error('验收测试批处理脚本仅支持 Windows。')
  }
  const scriptPath = resolveAcceptanceScriptPath()
  const outputRoot = getOutputRoot()
  await fs.mkdir(outputRoot, { recursive: true })
  const child = spawn(
    'cmd.exe',
    ['/d', '/c', 'start', '', scriptPath, '-OutputRoot', outputRoot],
    {
      cwd: path.dirname(scriptPath),
      detached: true,
      stdio: 'ignore',
      windowsHide: false
    }
  )
  child.unref()
  return { ok: true, path: scriptPath, outputRoot }
})

ipcMain.handle('art-text/prepare-output-task', async (event, options) => {
  const { outputRoot, mode, index, text, seed, startedAt, summaryDir } = options || {}
  return ensureUniqueTaskDir({ outputRoot, mode, index, text, seed, startedAt, summaryDir })
})

ipcMain.handle('art-text/write-task-artifacts', async (event, options) => {
  const {
    outputRoot,
    taskDir,
    taskName,
    paths = {},
    artifacts = {},
    metadata = {},
    runLog = '',
    usesTxt2Img = false,
    workflowArtifacts = null,
    summaryRow = null
  } = options || {}

  if (!taskDir || typeof taskDir !== 'string') {
    throw new Error('taskDir is required')
  }

  const root = path.resolve(outputRoot || path.dirname(taskDir))
  const resolvedTaskDir = path.resolve(taskDir)
  await fs.mkdir(resolvedTaskDir, { recursive: true })

  const targetPaths = {
    original: paths.original || path.join(resolvedTaskDir, 'original.png'),
    transparent: paths.transparent || path.join(resolvedTaskDir, 'transparent.png'),
    svg: paths.svg || path.join(resolvedTaskDir, 'result.svg'),
    preview: paths.preview || path.join(resolvedTaskDir, 'preview.png'),
    metadata: paths.metadata || path.join(resolvedTaskDir, 'metadata.json'),
    log: paths.log || path.join(resolvedTaskDir, 'run.log'),
    workflows: paths.workflows || path.join(resolvedTaskDir, 'workflows'),
    workflowApi: paths.workflowApi || path.join(resolvedTaskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: paths.workflowNodes || path.join(resolvedTaskDir, 'workflows', 'nodes.md'),
    modelDependencies: paths.modelDependencies || path.join(resolvedTaskDir, 'workflows', 'model_dependencies.json'),
    summary: paths.summary || path.join(root, 'batch_summary.csv')
  }

  const savedFiles = []
  for (const [key, filePath] of [
    ['original', targetPaths.original],
    ['transparent', targetPaths.transparent],
    ['svg', targetPaths.svg],
    ['preview', targetPaths.preview]
  ]) {
    const saved = await writeArtifactFile(filePath, artifacts[key], key === 'svg')
    if (saved) savedFiles.push(saved)
  }

  const shouldWriteMetadata = metadata !== undefined && metadata !== null
  const metadataPayload = shouldWriteMetadata
    ? {
        ...(metadata || {}),
        schema_version: metadata?.schema_version || 1,
        task_name: metadata?.task_name || taskName || path.basename(resolvedTaskDir),
        output_dir: resolvedTaskDir,
        paths: {
          original: 'original.png',
          transparent: 'transparent.png',
          svg: 'result.svg',
          preview: 'preview.png',
          metadata: 'metadata.json',
          log: 'run.log'
        },
        workflow_paths: usesTxt2Img
          ? {
              workflow_api: 'workflows/workflow_api.json',
              nodes: 'workflows/nodes.md',
              model_dependencies: 'workflows/model_dependencies.json'
            }
          : null
      }
    : null

  if (shouldWriteMetadata) {
    const metadataSaved = await writeArtifactFile(targetPaths.metadata, metadataPayload, true)
    if (metadataSaved) savedFiles.push(metadataSaved)
  }

  if (runLog !== undefined && runLog !== null && runLog !== '') {
    const logSaved = await writeArtifactFile(targetPaths.log, appendQualityMetricsToRunLog(runLog, metadataPayload || {}), true)
    if (logSaved) savedFiles.push(logSaved)
  }

  if (usesTxt2Img) {
    const wfApi = workflowArtifacts?.workflowApi || workflowArtifacts?.workflow_api
    const wfDeps = workflowArtifacts?.modelDependencies || workflowArtifacts?.model_dependencies
    const hasRealData = wfApi && typeof wfApi === 'object' && Object.keys(wfApi).length > 2
    const fallbackWorkflow = buildWorkflowArtifacts({
      metadata: metadataPayload || {},
      taskName,
      seed: metadataPayload?.generation?.seed,
      mode: metadataPayload?.mode,
      workflowApi: wfApi,
      modelDependencies: wfDeps
    })
    const workflow = hasRealData ? { ...fallbackWorkflow, ...workflowArtifacts } : fallbackWorkflow
    const wfSaved = await writeArtifactFile(targetPaths.workflowApi, workflow.workflowApi || workflow.workflow_api || {}, true)
    const nodesSaved = await writeArtifactFile(targetPaths.workflowNodes, workflow.workflowNodes || workflow.nodes || '', true)
    const depsSaved = await writeArtifactFile(targetPaths.modelDependencies, workflow.modelDependencies || workflow.model_dependencies || {}, true)
    savedFiles.push(...[wfSaved, nodesSaved, depsSaved].filter(Boolean))
  }

  if (summaryRow) {
    const summaryTarget = summaryRow.summary_path || targetPaths.summary
    if (summaryTarget) {
      await appendBatchSummaryCsv(summaryTarget, {
        ...extractQualityMetrics(metadataPayload || {}),
        ...summaryRow,
        task_name: summaryRow.task_name || taskName || path.basename(resolvedTaskDir),
        task_dir: summaryRow.task_dir || resolvedTaskDir,
        run_log_path: summaryRow.run_log_path || targetPaths.log
      })
    }
  }

  return { canceled: false, outputRoot: root, taskDir: resolvedTaskDir, taskName: taskName || path.basename(resolvedTaskDir), paths: targetPaths, filePaths: savedFiles }
})

ipcMain.handle('art-text/delete-output-dir', async (event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') {
    throw new Error('Invalid path')
  }
  // 安全校验：只允许删除 outputs 根目录下的任务子目录
  const root = getOutputRoot()
  const resolved = path.resolve(targetPath)
  if (!resolved.startsWith(path.resolve(root))) {
    throw new Error('只允许删除 outputs 目录下的任务子目录')
  }
  if (!fsSync.existsSync(resolved)) {
    return { ok: true, existed: false }
  }
  if (!fsSync.statSync(resolved).isDirectory()) {
    throw new Error('目标不是目录')
  }
  await fs.rm(resolved, { recursive: true, force: true })

  // 同步从 tasks-index.json 中移除已删除的目录记录
  await removeDeletedTaskFromIndex(root, resolved)

  return { ok: true, existed: true }
})

/**
 * 与 CLI batch.mjs 一致的批量输入解析：
 * 支持 | \t , 分隔，支持 CSV 引号转义，支持表头检测。
 */
function splitDelimitedLine(line, delimiter = ',') {
  const values = []
  let current = ''
  let quoted = false
  for (let i = 0; i < line.length; i++) {
    const char = line[i]
    const next = line[i + 1]
    if (char === '"' && quoted && next === '"') { current += '"'; i += 1 }
    else if (char === '"') { quoted = !quoted }
    else if (char === delimiter && !quoted) { values.push(current.trim()); current = '' }
    else { current += char }
  }
  values.push(current.trim())
  return values
}

function normalizeBatchItem(item, index = 0) {
  if (typeof item === 'string') {
    return { text: item.trim(), prompt: '', negative: '', seed: '', resolution: '' }
  }
  const raw = item || {}
  return {
    text: String(raw.text ?? raw.title ?? raw.word ?? raw.content ?? '').trim(),
    prompt: String(raw.prompt ?? raw.style ?? raw.description ?? '').trim(),
    negative: String(raw.negative ?? raw.negative_prompt ?? '').trim(),
    seed: raw.seed === undefined || raw.seed === '' ? '' : String(raw.seed),
    resolution: raw.resolution ? String(raw.resolution).trim() : '',
  }
}

function parseBatchInputText(content) {
  const trimmed = (content || '').trim()
  if (!trimmed) return []

  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    const parsed = JSON.parse(trimmed)
    const rows = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.items) ? parsed.items : [])
    return rows.map(normalizeBatchItem).filter(item => item.text || item.prompt)
  }

  const normalizeLine = (line) => String(line || '')
    .replace(/\uFEFF/g, '')
    .replace(/\uFF5C/g, '|')
    .replace(/\t\|/g, '|')
    .replace(/\|\t/g, '|')
    .trim()

  const lines = trimmed
    .split(/\r?\n/)
    .map(normalizeLine)
    .filter(line => line && !line.startsWith('#'))
  if (lines.length === 0) return []

  const first = lines[0].toLowerCase()
  const hasHeader = /\btext\b/.test(first) && /\bprompt\b/.test(first)
  const rows = hasHeader ? lines.slice(1) : lines
  const headerDelimiter = lines[0].includes('|') ? '|' : (lines[0].includes('\t') ? '\t' : ',')
  const headers = hasHeader ? splitDelimitedLine(lines[0], headerDelimiter).map(n => n.trim().toLowerCase()) : []

  return rows.map((line, index) => {
    const delimiter = line.includes('|') ? '|' : (line.includes('\t') ? '\t' : ',')
    const parts = splitDelimitedLine(line, delimiter)

    if (headers.length > 0) {
      const record = {}
      headers.forEach((key, i) => { record[key] = parts[i] || '' })
      return normalizeBatchItem(record, index)
    }

    return normalizeBatchItem({
      text: parts[0] || '',
      prompt: parts[1] || '',
      negative: parts[2] || '',
      seed: parts[3] || undefined,
      resolution: parts[4] || undefined,
    }, index)
  }).filter(item => item.text || item.prompt)
}

ipcMain.handle('art-text/parse-batch-input', async (event, content) => {
  return parseBatchInputText(content)
})

/**
 * 扫描输出根目录下的 tasks-index.json，返回所有任务索引条目。
 * 同时用于 CLI 产物发现（Desktop 启动时合并到历史列表）。
 */
async function scanHistoryFromFs(outputRoot) {
  const root = path.resolve(outputRoot || getOutputRoot())
  const indexPath = path.join(root, 'tasks-index.json')
  const entries = []

  try {
    const content = await fs.readFile(indexPath, 'utf8')
    entries.push(...normalizeHistoryIndexEntries(JSON.parse(content), root))
  } catch {
    // tasks-index.json 不存在 → 回退：扫描目录中的 task_* 目录
  }

  entries.push(...await scanLegacyTaskDirs(root))
  entries.push(...await scanNestedHistoryIndexes(root))
  entries.push(...await scanNestedLegacyTaskDirs(root))

  return dedupeHistoryEntries(entries)
}

function normalizeHistoryIndexEntries(index, indexRoot) {
  if (!Array.isArray(index)) return []
  return index
    .filter(entry => entry && typeof entry === 'object')
    .map(entry => {
      const normalized = {
        ...entry,
        outputRoot: entry.outputRoot || indexRoot
      }
      const isBatch = normalized.mode === 'batch' || normalized.inputParams?.mode === 'batch'
      const summaryPath = normalized.paths?.summary
      if (isBatch && summaryPath) {
        const summaryDir = path.dirname(summaryPath)
        normalized.mode = 'batch'
        normalized.taskDir = summaryDir
        normalized.paths = {
          ...(normalized.paths || {}),
          summary: summaryPath,
          summaryDir
        }
      }
      return normalized
    })
}

async function scanNestedHistoryIndexes(root, maxDepth = 4) {
  const results = []
  const rootResolved = path.resolve(root)
  const rootIndex = path.join(rootResolved, 'tasks-index.json')

  async function visit(dir, depth) {
    if (depth > maxDepth) return
    let children = []
    try {
      children = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }

    for (const child of children) {
      if (!child.isDirectory()) continue
      const childDir = path.join(dir, child.name)
      const indexPath = path.join(childDir, 'tasks-index.json')
      if (path.resolve(indexPath) !== path.resolve(rootIndex) && fsSync.existsSync(indexPath)) {
        try {
          const content = await fs.readFile(indexPath, 'utf8')
          results.push(...normalizeHistoryIndexEntries(JSON.parse(content), childDir))
        } catch { /* ignore unreadable nested indexes */ }
      }
      await visit(childDir, depth + 1)
    }
  }

  await visit(rootResolved, 1)
  return results
}

function dedupeHistoryEntries(entries) {
  const seen = new Set()
  return entries.filter((entry) => {
    const key = entry.taskDir ? `dir:${path.resolve(entry.taskDir).toLowerCase()}` : `id:${entry.id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

async function scanNestedLegacyTaskDirs(root, maxDepth = 4) {
  const results = []
  const rootResolved = path.resolve(root)

  async function visit(dir, depth) {
    if (depth > maxDepth) return
    let children = []
    try {
      children = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }

    const hasTaskChild = children.some(child => child.isDirectory() && /^task_/.test(child.name))
    if (path.resolve(dir) !== rootResolved && hasTaskChild) {
      results.push(...await scanLegacyTaskDirs(dir))
    }

    for (const child of children) {
      if (!child.isDirectory()) continue
      await visit(path.join(dir, child.name), depth + 1)
    }
  }

  await visit(rootResolved, 1)
  return results
}

/**
 * 兼容扫描：当 tasks-index.json 不存在时，扫描 outputs/ 下的 task_* 目录。
 */
async function scanLegacyTaskDirs(root) {
  const entries = []
  try {
    const dirs = await fs.readdir(root)
    const taskDirs = dirs.filter(name => /^task_/.test(name))

    for (const name of taskDirs) {
      const taskDir = path.join(root, name)
      const stat = await fs.stat(taskDir)
      if (!stat.isDirectory()) continue

      const metadataPath = path.join(taskDir, 'metadata.json')
      let metadata = null
      try {
        const metaText = await fs.readFile(metadataPath, 'utf8')
        metadata = JSON.parse(metaText)
      } catch { /* 无 metadata 也继续 */ }

      const isBatch = fsSync.existsSync(path.join(taskDir, 'batch_summary.csv'))
      // 检查是否有子目录（batch 子任务）
      let hasSubDirs = false
      try {
        const children = await fs.readdir(taskDir)
        hasSubDirs = children.some(c => /^task_/.test(c))
      } catch { /* 忽略 */ }

      const mode = isBatch || hasSubDirs ? 'batch' : (metadata?.mode || 'single')
      const title = metadata?.task_name || metadata?.generation?.text || name
      const status = metadata?.error ? '失败' : '完成'

      entries.push({
        id: metadata?.task_id ? Number(metadata.task_id) : Date.now(),
        mode,
        title: String(title),
        time: metadata?.generation?.started_at || new Date().toISOString(),
        status,
        taskDir,
        outputRoot: root,
        paths: {
          summary: path.join(taskDir, 'batch_summary.csv'),
          summaryDir: taskDir,
          original: path.join(taskDir, 'original.png'),
          transparent: path.join(taskDir, 'transparent.png'),
          svg: path.join(taskDir, 'result.svg'),
          preview: path.join(taskDir, 'preview.png'),
          metadata: metadataPath,
          log: path.join(taskDir, 'run.log'),
        },
        inputParams: { mode },
        _legacy: true,
      })
    }
  } catch { /* 目录不存在或无法读取 */ }

  return entries
}

/**
 * 从 tasks-index.json 中移除已删除目录对应的条目。
 */
async function removeDeletedTaskFromIndex(root, deletedDir) {
  const indexPath = path.join(root, 'tasks-index.json')
  try {
    const content = await fs.readFile(indexPath, 'utf8')
    let index = JSON.parse(content)
    const before = index.length
    index = index.filter(e => !e.taskDir || !path.resolve(e.taskDir).startsWith(path.resolve(deletedDir)))
    if (index.length < before) {
      await fs.writeFile(indexPath, JSON.stringify(index, null, 2), 'utf8')
    }
  } catch { /* 索引不存在或不合法，静默忽略 */ }
}

ipcMain.handle('art-text/scan-fs-history', async (event, outputRoot) => {
  return scanHistoryFromFs(outputRoot)
})

ipcMain.handle('art-text/read-output-file', async (event, options) => {
  const { filePath, encoding = 'dataUrl', mime = 'application/octet-stream' } = options || {}
  if (!filePath || typeof filePath !== 'string') {
    throw new Error('filePath is required')
  }
  const buffer = await fs.readFile(filePath)
  if (encoding === 'text') {
    return buffer.toString('utf8')
  }
  return `data:${mime};base64,${buffer.toString('base64')}`
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

    const safeKey = String(key).replace(/[^a-zA-Z0-9_-]+/g, '-') || 'artifact'
    const filePath = path.join(folder, `${fileBase}_${safeKey}.${ext}`)
    await fs.writeFile(filePath, buffer)
    savedFiles.push(filePath)
  }

  return { canceled: false, filePaths: savedFiles }
})

ipcMain.handle('art-text/shutdown-backends', async () => {
  shutdownBackends()
  return { ok: true, message: '已向两个后端发送关闭请求' }
})

ipcMain.handle('art-text/get-startup-status', async () => {
  return { ...startupState }
})

ipcMain.handle('art-text/download-models', async () => {
  const backendDir = getBackendDir()
  if (!backendDir) {
    throw new Error('模型下载仅在生产打包版本中可用')
  }

  const ps1Path = path.join(backendDir, 'download-models.ps1')
  if (!fsSync.existsSync(ps1Path)) {
    throw new Error('未找到模型下载脚本')
  }

  // 向主窗口发送进度
  const sendProgress = (data) => {
    if (mainWin && !mainWin.isDestroyed()) {
      mainWin.webContents.send('splash:progress', data)
    }
  }

  sendProgress({ step: 2, phase: 'downloading', message: '正在准备下载...', percent: 0, fileIndex: 0 })

  try {
    const result = await downloadModels(backendDir, sendProgress)
    if (result.fail === 0) {
      startupState.modelsReady = true
      startupState.modelsSkipped = false
    }
    sendProgress({ step: 2, phase: 'complete', message: '模型下载完成', percent: 100, result })
    return { ok: true, ...result }
  } catch (err) {
    sendProgress({ step: 2, phase: 'error', message: err.message, percent: 0 })
    throw err
  }
})

function shutdownBackends() {
  // 发送优雅关闭请求
  for (const url of SHUTDOWN_URLS) {
    try {
      const u = new URL(url)
      const req = net.request({
        method: 'POST',
        protocol: u.protocol,
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
      })
      req.on('error', () => {})
      req.setHeader('Content-Type', 'application/json')
      req.write(JSON.stringify({}))
      req.end()
    } catch {
      // 后端可能本来就已关闭，静默忽略
    }
  }

  // 硬杀整棵进程树（兜底）：后端可能再 spawn ComfyUI / Python 子进程。
  killProcessTree(txt2imgProc)
  killProcessTree(vectorizerProc)
  txt2imgProc = null
  vectorizerProc = null
}

// 全局退出函数 — 杀后端 + 杀所有 PowerShell 子进程 + 退出 app
function forceQuit() {
  shutdownBackends()
  // 预加载阶段可能还在解压引擎或下载模型，必须杀整棵进程树。
  killProcessTree(modelDownloadProc)
  killProcessTree(engineDownloadProc)
  modelDownloadProc = null
  engineDownloadProc = null
  app.exit(0)
}

function shutdownPreloadTasks() {
  killProcessTree(modelDownloadProc)
  killProcessTree(engineDownloadProc)
  modelDownloadProc = null
  engineDownloadProc = null
}

app.whenReady().then(async () => {
  if (app.isPackaged) {
    // ── 生产模式：显示启动画面 → 启动后端 → 打开主窗口 ──
    splashWin = createSplashWindow()

    splashWin.on('closed', () => {
      splashWin = null
    })

    // 执行启动序列
    let result = await runStartupSequence(splashWin)

    // 处理重试
    while (result && !result.success && result.error) {
      // 等待用户在错误界面选择重试或退出
      const action = await waitForSplashAction()
      if (action === 'retry') {
        startupError = null
        result = await runStartupSequence(splashWin)
      } else {
        break
      }
    }

    if (result && result.success) {
      // 短暂延迟让用户看到"完成"状态
      await new Promise(r => setTimeout(r, 600))
      if (splashWin && !splashWin.isDestroyed()) {
        splashWin.close()
      }
      showMainWindow()
    }
    // 如果有未处理的错误且用户没选择重试，splash 上的"退出"按钮会触发 app.quit()
  } else {
    // ── 开发模式：直接打开主窗口（行为不变） ──
    mainWin = createMainWindow()
    mainWin.on('closed', () => {
      mainWin = null
    })
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (app.isPackaged) {
        showMainWindow()
      } else {
        mainWin = createMainWindow()
        mainWin.on('closed', () => { mainWin = null })
      }
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', (event) => {
  event.preventDefault()
  shutdownBackends()
  shutdownPreloadTasks()
  // 延迟退出，确保 TCP 包被 OS 内核发送
  setTimeout(() => { app.exit(0) }, 300)
})

// 捕获所有未预期的错误，确保不留下孤儿进程
process.on('uncaughtException', () => {
  shutdownBackends()
  shutdownPreloadTasks()
  app.exit(1)
})
