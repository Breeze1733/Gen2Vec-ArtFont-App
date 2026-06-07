# 预加载阶段后端进度读取方案

本文档整理当前桌面端“预加载阶段”的核心进度读取逻辑，供后续设计其他预加载脚本时复用。

这里的“预加载阶段”指应用正式进入主功能前，需要先准备本地资源、启动服务、下载模型、解压引擎或执行其他长耗时任务的阶段。该阶段的任务通常由 Electron 主进程启动外部脚本或后端进程，前端只负责展示进度与用户操作。

## 当前实现

当前模型下载链路由以下文件组成：

| 层级 | 文件 | 职责 |
| --- | --- | --- |
| 预加载脚本 | `scripts/download-models.ps1` | 执行模型校验、续传下载、完成标记、取消清理，并在 `-Electron` 模式输出结构化进度 |
| Electron 主进程 | `apps/desktop/electron/main.cjs` | spawn PowerShell，解析脚本 stdout，轮询文件大小推算速度/ETA，通过 IPC 推送进度 |
| preload 桥 | `apps/desktop/electron/preload.cjs` | 暴露 `downloadModels()`、`onSplashProgress()`、`removeSplashProgressListener()` |
| 启动页 | `apps/desktop/electron/splash.html` | 启动时展示步骤、总进度、当前文件进度、速度、ETA |
| 主窗口 | `apps/desktop/src/renderer/App.vue` | 用户稍后下载模型时，订阅同一进度事件并展示下载面板 |

整体数据流：

```text
PowerShell script stdout
  -> Electron main process parses MODELDL lines
  -> mainWin/splashWin.webContents.send('splash:progress', data)
  -> preload exposes window.artTextApp.onSplashProgress(callback)
  -> renderer updates reactive progress state
  -> UI renders progress, speed, ETA, result summary
```

## 脚本输出协议

预加载脚本在 Electron 模式下必须只输出机器可解析的结构化行，避免混入普通日志。

统一格式：

```text
<PREFIX><TYPE>|<field1>|<field2>|...
```

当前模型下载脚本使用：

```text
MODELDL:<TYPE>|...
```

常用事件：

| TYPE | 示例 | 含义 |
| --- | --- | --- |
| `READY` | `MODELDL:READY` | 脚本已进入主流程 |
| `ENGINE_OK` | `MODELDL:ENGINE_OK` | 必要本地引擎存在 |
| `ENGINE_MISSING` | `MODELDL:ENGINE_MISSING|<path>` | 必要本地引擎缺失 |
| `TOTAL` | `MODELDL:TOTAL|10` | 任务总数 |
| `CHECK` | `MODELDL:CHECK|file|subdir|local|remote` | 正在校验本地/远程文件大小 |
| `RESUME` | `MODELDL:RESUME|file|subdir|local` | 将基于本地文件续传 |
| `START` | `MODELDL:START|file|subdir|size` | 某个任务开始 |
| `DONE` | `MODELDL:DONE|file|subdir|actualSize` | 某个任务完成 |
| `SKIP` | `MODELDL:SKIP|file|subdir|actualSize` | 某个任务已存在并跳过 |
| `ERROR` | `MODELDL:ERROR|file|subdir|code|message` | 某个任务失败 |
| `COMPLETE` | `MODELDL:COMPLETE|ok|skip|fail` | 全部任务结束 |

设计新脚本时建议：

- 每一行只表达一个事件。
- 字段分隔符统一用 `|`。
- 文件名、路径、错误信息尽量不要包含 `|`；必要时对字段做 URL encode 或 Base64。
- 普通人类可读日志只在非 Electron 模式输出。
- Electron 模式下不要使用会污染 stdout 的下载工具进度条。

## 主进程解析逻辑

主进程负责启动脚本：

```js
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
```

stdout 解析规则：

```js
const lines = chunk.toString().split(/\r?\n/).filter(Boolean)
for (const line of lines) {
  if (!line.startsWith('MODELDL:')) continue
  const parts = line.substring(8).split('|')
  const type = parts[0]
  // switch(type) -> progress object
}
```

主进程输出给前端的进度对象推荐保持稳定字段：

```js
{
  step: 2,
  phase: 'downloading' | 'complete' | 'error' | 'prompt' | 'checking' | 'resuming',
  message: '',
  percent: 0,
  fileIndex: 1,
  totalFiles: 10,
  fileName: '',
  fileSize: '',
  subdir: '',
  speed: '',
  eta: '',
  filePercent: -1,
  detail: '',
  result: { ok: 0, skip: 0, fail: 0 }
}
```

当前实现还会在主进程每 2 秒轮询正在下载的文件大小，推算：

- `speed`：下载速度，例如 `12.5 MB/s`
- `eta`：剩余时间，例如 `8m20s`
- `filePercent`：当前文件百分比

注意：如果一个预加载脚本内部并发多个任务，而 UI 只有单文件进度条，则 `speed/eta/filePercent` 只能作为当前活跃文件的近似展示。需要精确展示多任务时，应扩展为 `files: []` 数组。

## IPC 事件桥

主进程向窗口推送：

```js
win.webContents.send('splash:progress', data)
```

preload 暴露监听接口：

```js
contextBridge.exposeInMainWorld('artTextApp', {
  downloadModels: () => ipcRenderer.invoke('art-text/download-models'),
  onSplashProgress: (callback) => {
    ipcRenderer.on('splash:progress', (_event, data) => callback(data))
  },
  removeSplashProgressListener: () => {
    ipcRenderer.removeAllListeners('splash:progress')
  },
})
```

后续模块复用时，可以保留 `splash:progress` 作为全局预加载进度通道，也可以按模块拆分事件名，例如：

```text
preload:model-progress
preload:engine-progress
preload:cache-progress
```

如果多种预加载任务可能同时进行，建议在 progress 对象里加：

```js
taskId: 'model-download',
taskName: '模型下载'
```

## 前端订阅逻辑

renderer 侧通过 API 包装层订阅：

```js
onSplashProgress((data) => {
  if (!data || typeof data !== 'object') return

  if (data.phase) progress.phase = data.phase
  if (data.message) progress.message = data.message
  if (data.fileIndex !== undefined) progress.current = data.fileIndex || 0
  if (data.totalFiles !== undefined) progress.total = data.totalFiles || 0
  if (data.fileName !== undefined) progress.fileName = data.fileName || ''
  if (data.fileSize !== undefined) progress.fileSize = data.fileSize || ''
  if (data.subdir !== undefined) progress.subdir = data.subdir || ''
  if (data.percent !== undefined) progress.percent = clampPercent(data.percent)
  if (data.filePercent !== undefined) progress.filePercent = clampPercent(data.filePercent)
  if (data.speed !== undefined) progress.speed = data.speed || ''
  if (data.eta !== undefined) progress.eta = data.eta || ''
  if (data.result) progress.result = data.result
})
```

前端应做防御性处理：

- `percent < 0` 表示未知进度，UI 可使用不确定进度条。
- `filePercent < 0` 表示当前文件进度不可用。
- `totalFiles === 0` 时不要计算 `current / total`。
- 完成后保留 `result`，不要立即清空进度，否则用户看不到最终汇总。
- 组件卸载或任务结束时调用 `removeSplashProgressListener()`，避免重复订阅。

## 取消与清理

预加载脚本必须考虑用户中断。

PowerShell 脚本建议包含：

- 全局记录当前 `Start-Job` 列表。
- `trap` 捕获中断/异常。
- 停止 `dl_*` 后台 Job。
- 兜底停止与当前下载任务相关的下载器进程。
- 输出 `ERROR` 或以非零退出码结束。

当前模型下载脚本中断后会：

```text
MODELDL:ERROR|download-models.ps1|script|130|用户中断，已停止后台下载任务
```

主进程收到非零退出码时，如果没有具体文件失败事件，应转成统一错误：

```js
reject(new Error(`模型下载脚本异常退出 (退出码: ${code})`))
```

## 设计新预加载脚本的复用模板

设计其他模块预加载任务时，建议按以下顺序实现：

1. 定义脚本 Electron 模式参数，例如 `-Electron`。
2. 定义唯一前缀，例如 `CACHELD:`、`ENGINEDL:`、`MODELDL:`。
3. 输出 `READY`、`TOTAL`、`START`、`DONE/SKIP/ERROR`、`COMPLETE`。
4. 非 Electron 模式输出人类可读日志，Electron 模式只输出结构化行。
5. 主进程 spawn 脚本并逐行解析前缀。
6. 主进程转换为统一 progress object。
7. preload 暴露 invoke 入口和 progress event 监听。
8. 前端订阅事件并更新 reactive state。
9. 任务结束后保留 result summary，并移除监听器。
10. 为 Ctrl+C、窗口关闭、应用退出补清理逻辑。

## 最小协议示例

脚本输出：

```text
MYLOAD:READY
MYLOAD:TOTAL|3
MYLOAD:START|cache-a|assets|120 MB
MYLOAD:DONE|cache-a|assets|120 MB
MYLOAD:START|cache-b|assets|80 MB
MYLOAD:ERROR|cache-b|assets|1|network timeout
MYLOAD:COMPLETE|1|0|1
```

主进程转换：

```js
{
  phase: 'downloading',
  percent: 33,
  fileIndex: 1,
  totalFiles: 3,
  fileName: 'cache-a',
  fileSize: '120 MB'
}
```

前端展示：

```text
正在预加载 cache-a (1/3)
总进度 33%
```

## 当前模型下载链路的静态检查点

当前实现静态检查应覆盖：

- `download-models.ps1` Electron 模式输出是否仍是 `MODELDL:TYPE|...`。
- `main.cjs` 是否按 `line.substring(8).split('|')` 解析。
- `main.cjs` 是否向 `splash:progress` 推送 `percent/fileIndex/totalFiles/fileName/fileSize/speed/eta/filePercent/result`。
- `preload.cjs` 是否暴露 `onSplashProgress` 和 `removeSplashProgressListener`。
- `App.vue` 是否订阅事件并保存所有字段。
- `npm run build` 是否通过。
- `node --check apps/desktop/electron/main.cjs` 是否通过。

