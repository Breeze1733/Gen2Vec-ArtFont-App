const { contextBridge, ipcRenderer } = require('electron')

// Exposed Electron API for renderer. Keep stable method names here and
// document them in docs/electron-ipc.md.
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
  'openExternal'
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
  shutdownBackends: () => ipcRenderer.invoke('art-text/shutdown-backends')
})
