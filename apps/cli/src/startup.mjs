/**
 * startup.mjs — CLI 后端管理模块
 *
 * 让 CLI 像 Electron 一样负责后端进程的完整生命周期：
 *   1. 检查同级 backend/ 目录
 *   2. 检查/解压 ComfyUI 引擎
 *   3. 检查/下载 AI 模型
 *   4. spawn txt2img-backend + vectorizer-backend
 *   5. 轮询 healthz → 就绪
 *   6. 执行用户命令
 *   7. 退出时 POST /shutdown → kill 子进程
 *
 * 与 Electron main.cjs 的 runStartupSequence() 逻辑完全对应，
 * 区别只在进度输出方式：Electron 发 IPC 给 splash，CLI 用 console.log。
 */

import { spawn } from 'node:child_process'
import { resolve, dirname, join } from 'node:path'
import { existsSync, accessSync } from 'node:fs'
import { constants } from 'node:fs'
import { createInterface } from 'node:readline'
import { createServer } from 'node:net'

// ── 端口检测 ──

function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = createServer()
    server.once('error', () => resolve(true))
    server.once('listening', () => {
      server.close()
      resolve(false)
    })
    server.listen(port, '127.0.0.1')
  })
}

// ── 后端路径解析 ──

const TXT2IMG_HEALTHZ = process.env.TXT2IMG_BACKEND_URL
  ? new URL(process.env.TXT2IMG_BACKEND_URL).origin + '/healthz'
  : 'http://127.0.0.1:9001/healthz'

const VECTORIZER_HEALTHZ = process.env.VECTORIZER_BACKEND_URL
  ? new URL(process.env.VECTORIZER_BACKEND_URL).origin + '/healthz'
  : 'http://127.0.0.1:8000/healthz'

/**
 * 解析 backend/ 目录路径。
 * Node.js SEA 模式: process.execPath 是 exe 路径，找 exe 同级的 backend/
 * 普通 node 模式: process.argv[1] 是 gen2vec.mjs 路径
 */
export function resolveBackendDir() {
  // 先找 exe 同级的 backend/
  const byExe = join(dirname(process.execPath), 'backend')
  if (existsSync(byExe)) return byExe

  // 再找脚本同级的 backend/（开发模式）
  const byScript = join(dirname(process.argv[1] || '.'), '..', 'backend')
  if (existsSync(byScript)) return byScript

  return null
}

// ── ComfyUI 引擎管理 ──

function getComfyUIExtractDir(backendDir) {
  return join(backendDir, 'ComfyUI_windows_portable_nvidia')
}

function getComfyUIPortableDir(backendDir) {
  return join(getComfyUIExtractDir(backendDir), 'ComfyUI_windows_portable')
}

function isComfyUIExtracted(backendDir) {
  const sentinel = join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'main.py')
  return existsSync(sentinel)
}

async function extractComfyUI(backendDir) {
  const engineExe = join(backendDir, 'ComfyUI-Engine.exe')
  if (!existsSync(engineExe)) {
    throw new Error(`未找到推理引擎文件: ${engineExe}`)
  }

  process.stdout.write('  [1/4] 推理引擎... 正在解压 (ComfyUI-Engine.exe)...\r')

  return new Promise((resolve, reject) => {
    const proc = spawn(engineExe, [], {
      cwd: backendDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      // Linux: 如果 ComfyUI-Engine 是 7z SFX for Linux，实际传递
    })

    proc.on('error', (err) => reject(new Error(`启动解压程序失败: ${err.message}`)))

    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`推理引擎解压失败 (退出码: ${code})`))
        return
      }
      if (!isComfyUIExtracted(backendDir)) {
        reject(new Error('推理引擎解压后未找到 ComfyUI/main.py，可能解压不完整'))
        return
      }
      process.stdout.write('  [1/4] 推理引擎... 解压完成 ✓\n')
      resolve()
    })
  })
}

// ── 模型管理 ──

function getComfyUIModelsDir(backendDir) {
  return join(getComfyUIPortableDir(backendDir), 'ComfyUI', 'models')
}

function getModelSentinelFile(backendDir) {
  return join(getComfyUIModelsDir(backendDir), 'vae', 'ae.safetensors')
}

async function checkModelsExist(backendDir) {
  try {
    accessSync(getModelSentinelFile(backendDir), constants.F_OK)
    return true
  } catch {
    return false
  }
}

function downloadModels(backendDir) {
  return new Promise((resolve, reject) => {
    const ps1Path = join(backendDir, 'download-models.ps1')
    if (!existsSync(ps1Path)) {
      reject(new Error(`未找到模型下载脚本: ${ps1Path}`))
      return
    }

    const proc = spawn('powershell.exe', [
      '-NoProfile', '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-File', ps1Path, '-Electron',
    ], {
      cwd: backendDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })

    let totalFiles = 0
    let completed = 0
    let failed = 0
    let currentFile = ''

    const rl = createInterface({ input: proc.stdout })
    rl.on('line', (line) => {
      if (!line.startsWith('MODELDL:')) return
      const parts = line.slice(8).split('|')
      const type = parts[0]

      switch (type) {
        case 'TOTAL':
          totalFiles = parseInt(parts[1], 10) || 0
          break
        case 'START':
          currentFile = parts[1] || ''
          const idx = parseInt(parts[2]?.split('/')[0], 10) || 0
          process.stdout.write(`  [2/4] 模型下载... (${idx + 1}/${totalFiles}) ${currentFile}\r`)
          break
        case 'DONE':
        case 'SKIP':
          completed++
          break
        case 'ERROR':
          completed++
          failed++
          break
        case 'COMPLETE':
          const ok = parseInt(parts[1], 10) || 0
          const fail = parseInt(parts[3], 10) || 0
          if (fail > 0) {
            process.stdout.write(`  [2/4] 模型下载... ${ok} 成功, ${fail} 失败\n`)
          } else {
            process.stdout.write(`  [2/4] 模型下载... 全部完成 ✓\n`)
          }
          break
      }
    })

    proc.stderr.on('data', (chunk) => {
      process.stderr.write('[download-models] ' + chunk.toString())
    })

    proc.on('error', (err) => reject(new Error(`启动下载脚本失败: ${err.message}`)))

    proc.on('close', (code) => {
      if (code !== 0 && failed === 0) {
        reject(new Error(`模型下载脚本异常退出 (退出码: ${code})`))
        return
      }
      resolve({ ok: completed - failed, fail: failed })
    })
  })
}

// ── 后端进程生命周期 ──

let backendProcs = []

function spawnBackend(exePath, cwd) {
  if (!existsSync(exePath)) {
    throw new Error(`未找到后端程序: ${exePath}`)
  }
  const proc = spawn(exePath, [], {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  proc.on('error', (err) => console.error(`[backend] ${exePath} 进程错误:`, err.message))
  backendProcs.push(proc)
  return proc
}

async function waitForHealthz(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(3000) })
      if (resp.ok) return true
    } catch {
      // 尚未就绪，继续轮询
    }
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}

async function checkBackendHealth(port, expectedService) {
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/healthz`, { signal: AbortSignal.timeout(2000) })
    if (resp.ok) {
      const body = await resp.json().catch(() => ({}))
      if (body.service === expectedService) return { running: true, matches: true }
      return { running: true, matches: false }
    }
  } catch { /* 无响应 */ }
  return { running: false, matches: false }
}

async function startBackends(backendDir) {
  // ── 矢量化后端 (8000) ──
  process.stdout.write('  [3/4] 启动服务...\r')
  const vecExe = join(backendDir, 'vectorizer-backend.exe')

  const vecHealth = await checkBackendHealth(8000, 'vectorizer-api')
  if (vecHealth.running && vecHealth.matches) {
    process.stdout.write('  [3/4] 矢量化服务... 已在线 (复用) ✓\n')
  } else if (vecHealth.running && !vecHealth.matches) {
    throw new Error('端口 8000 已被其他程序占用')
  } else {
    spawnBackend(vecExe, backendDir)
    const ready = await waitForHealthz('http://127.0.0.1:8000/healthz')
    if (!ready) throw new Error('矢量化服务启动超时')
    process.stdout.write('  [3/4] 矢量化服务... ✓ (127.0.0.1:8000)\n')
  }

  // ── 文生图后端 (9001) ──
  process.stdout.write('  [3/4] 启动服务...\r')
  const t2iExe = join(backendDir, 'txt2img-backend.exe')

  const t2iHealth = await checkBackendHealth(9001, 'txt2img-api')
  if (t2iHealth.running && t2iHealth.matches) {
    process.stdout.write('  [3/4] 文生图服务... 已在线 (复用) ✓\n')
  } else if (t2iHealth.running && !t2iHealth.matches) {
    throw new Error('端口 9001 已被其他程序占用')
  } else {
    spawnBackend(t2iExe, backendDir)
    const ready = await waitForHealthz('http://127.0.0.1:9001/healthz')
    if (!ready) throw new Error('文生图服务启动超时')
    process.stdout.write('  [3/4] 文生图服务... ✓ (127.0.0.1:9001)\n')
  }
}

// ── 启动编排 ──

export async function runStartupSequence() {
  const backendDir = resolveBackendDir()
  let modelsSkipped = false

  if (!backendDir) {
    console.log('  [INFO] backend/ 目录不存在，跳过后端管理')
    return { success: true, modelsSkipped: false }
  }

  console.log('  ──────────────────────────────')

  // ── 步骤 1: 检查 / 解压 ComfyUI 引擎 ──
  process.stdout.write('  [1/4] 推理引擎... 检查中\r')
  const comfyuiExe = join(backendDir, 'ComfyUI-Engine.exe')

  if (!existsSync(comfyuiExe)) {
    process.stdout.write('  [1/4] 推理引擎... 跳过 (未包含引擎包)\n')
  } else if (!isComfyUIExtracted(backendDir)) {
    await extractComfyUI(backendDir)
  } else {
    process.stdout.write('  [1/4] 推理引擎... 已就绪 (跳过)\n')
  }

  // ── 步骤 2: 检查 / 下载模型 ──
  process.stdout.write('  [2/4] 模型下载... 检查中\r')
  const modelsExist = await checkModelsExist(backendDir)
  const ps1Path = join(backendDir, 'download-models.ps1')

  if (modelsExist) {
    process.stdout.write('  [2/4] 模型下载... 已就绪 (跳过)\n')
  } else if (!existsSync(ps1Path)) {
    process.stdout.write('  [2/4] 模型下载... 跳过 (未包含下载脚本)\n')
    modelsSkipped = true
  } else {
    process.stdout.write('  [2/4] 模型下载... 首次运行需要下载 (约 58 GB)\n')
    process.stdout.write('        是否下载？[Y/n] ')

    // 终端读取用户输入
    const answer = await new Promise((resolve) => {
      process.stdin.once('data', (data) => {
        resolve(data.toString().trim().toLowerCase())
      })
    })

    if (answer === '' || answer === 'y' || answer === 'yes') {
      await downloadModels(backendDir)
      modelsSkipped = false
    } else {
      process.stdout.write('  [2/4] 模型下载... 已跳过，文生图使用本地降级引擎\n')
      modelsSkipped = true
    }
  }

  // ── 步骤 3: 启动后端服务 ──
  await startBackends(backendDir)

  // ── 就绪 ──
  console.log('  [4/4] 就绪')
  console.log('  ──────────────────────────────')

  return { success: true, modelsSkipped }
}

// ── 退出清理 ──

export async function shutdownBackendsProcesses() {
  // 发送 POST /shutdown 优雅关闭
  const backends = [
    { url: process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001', path: '/shutdown' },
    { url: process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000', path: '/shutdown' },
  ]

  for (const { url, path } of backends) {
    try {
      const u = new URL(url)
      const shutdownUrl = `${u.protocol}//${u.hostname}:${u.port}${path}`
      await fetch(shutdownUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
    } catch {
      // 后端可能本来已关闭
    }
  }

  // 硬杀直接子进程（兜底）
  for (const proc of backendProcs) {
    try { if (!proc.killed) proc.kill() } catch {}
  }
}
