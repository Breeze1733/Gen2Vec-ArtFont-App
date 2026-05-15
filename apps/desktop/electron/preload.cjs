const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('artTextApp', {
  platform: process.platform,
  vectorize: (payload) => ipcRenderer.invoke('art-text/vectorize', payload),
  generate: (payload) => ipcRenderer.invoke('art-text/generate', payload),
  saveFile: (options) => ipcRenderer.invoke('art-text/save-file', options)
})
