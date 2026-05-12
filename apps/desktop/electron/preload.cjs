const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('artTextApp', {
  platform: process.platform
})
