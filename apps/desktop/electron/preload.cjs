const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('artTextApp', {
  platform: process.platform,
  getPlatform: () => process.platform,
  getAppVersion: () => ipcRenderer.invoke('art-text/get-app-version'),
  isDev: () => ipcRenderer.invoke('art-text/is-dev'),
  vectorize: (payload) => ipcRenderer.invoke('art-text/vectorize', payload),
  generate: (payload) => ipcRenderer.invoke('art-text/generate', payload),
  saveFile: (options) => ipcRenderer.invoke('art-text/save-file', options),
  saveResults: (options) => ipcRenderer.invoke('art-text/save-results', options),
  notify: (options) => ipcRenderer.invoke('art-text/notify', options),
  openExternal: (url) => ipcRenderer.invoke('art-text/open-external', url)
})
