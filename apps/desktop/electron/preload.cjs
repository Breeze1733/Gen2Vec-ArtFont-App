const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('artTextApp', {
  platform: process.platform,
  generate: (payload) => ipcRenderer.invoke('art-text/generate', payload),
  saveFile: (options) => ipcRenderer.invoke('art-text/save-file', options)
})
