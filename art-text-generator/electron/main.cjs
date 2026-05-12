const { app, BrowserWindow } = require('electron')
const path = require('path')

function createWindow() {
	const win = new BrowserWindow({
		width: 800,
		height: 700,
		webPreferences: {
			preload: path.join(__dirname, 'preload.cjs'),
			contextIsolation: true,
			nodeIntegration: false
		}
	})

	// 开发时加载 Vite 开发服务器，打包后加载本地文件
	if (process.env.VITE_DEV_SERVER_URL) {
		win.loadURL(process.env.VITE_DEV_SERVER_URL)
		win.webContents.openDevTools() // 可注释掉不让用户看到控制台
	} else {
		win.loadFile(path.join(__dirname, '../dist/index.html'))
	}
}

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
	if (process.platform !== 'darwin') app.quit()
})