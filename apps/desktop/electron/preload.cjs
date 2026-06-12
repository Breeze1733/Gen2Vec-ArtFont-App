const { contextBridge, ipcRenderer } = require('electron')

// Exposed Electron API for renderer.
const API_VERSION = '1.1.0'
const API_METHODS = [
  'getPlatform',
  'getAppVersion',
  'isDev',
  'vectorize',
  'generate',
  'saveFile',
  'saveResults',
  'prepareOutputTask',
  'writeTaskArtifacts',
  'readOutputFile',
  'deleteOutputDir',
  'openPath',
  'notify',
  'openExternal',
  'getStartupStatus',
  'downloadModels',
  'launchAcceptanceTest',
  'shutdownBackends',
  'scanFsHistory'
]

/**
 * Expose a minimal, safe API to the renderer process.
 * Methods return Promises where appropriate and proxy to ipcRenderer.invoke.
 */
contextBridge.exposeInMainWorld('artTextApp', {
  // API metadata
  apiVersion: API_VERSION,
  platform: process.platform,
  listMethods: () => API_METHODS.slice(),

  // Utilities
  getPlatform: () => process.platform,
  getAppVersion: () => ipcRenderer.invoke('art-text/get-app-version'),
  isDev: () => ipcRenderer.invoke('art-text/is-dev'),

  // Core actions
  vectorize: (payload) => ipcRenderer.invoke('art-text/vectorize', payload),
  generate: (payload) => ipcRenderer.invoke('art-text/generate', payload),

  // File helpers
  saveFile: (options) => ipcRenderer.invoke('art-text/save-file', options),
  saveResults: (options) => ipcRenderer.invoke('art-text/save-results', options),
  prepareOutputTask: (options) => ipcRenderer.invoke('art-text/prepare-output-task', options),
  writeTaskArtifacts: (options) => ipcRenderer.invoke('art-text/write-task-artifacts', options),
  readOutputFile: (options) => ipcRenderer.invoke('art-text/read-output-file', options),
  deleteOutputDir: (targetPath) => ipcRenderer.invoke('art-text/delete-output-dir', targetPath),
  openPath: (targetPath) => ipcRenderer.invoke('art-text/open-path', targetPath),

  // Misc
  notify: (options) => ipcRenderer.invoke('art-text/notify', options),
  openExternal: (url) => ipcRenderer.invoke('art-text/open-external', url),
  shutdownBackends: () => ipcRenderer.invoke('art-text/shutdown-backends'),

  // 文件系统历史扫描（发现 CLI 产生的产物）
  scanFsHistory: (outputRoot) => ipcRenderer.invoke('art-text/scan-fs-history', outputRoot),

  // Startup & model management (生产打包模式)
  getStartupStatus: () => ipcRenderer.invoke('art-text/get-startup-status'),
  downloadModels: () => ipcRenderer.invoke('art-text/download-models'),
  launchAcceptanceTest: () => ipcRenderer.invoke('art-text/launch-acceptance-test'),

  // Splash / progress events (send/on 模式，非 invoke)
  onSplashProgress: (callback) => {
    ipcRenderer.on('splash:progress', (_event, data) => callback(data))
  },
  removeSplashProgressListener: () => {
    ipcRenderer.removeAllListeners('splash:progress')
  },
  sendSplashAction: (action) => {
    ipcRenderer.send('splash:action', action)
  }
})
