# Electron IPC / Preload API 说明（桌面端）

此文档描述 `apps/desktop` 中通过 Electron `preload.cjs` 暴露给渲染进程的接口，以及前端如何调用这些 API。所有方法都通过 `window.artTextApp` 可用。

## 1. 概览

渲染端可以通过 `window.artTextApp` 访问下面的方法：

- `apiVersion: string` — API 版本号。用于兼容性检查。
- `platform: string` — 当前运行平台（nodejs 的 process.platform）。
- `listMethods(): string[]` — 返回支持的方法名列表。
- `getPlatform(): string` — 返回平台字符串（同步）。
- `getAppVersion(): Promise<string>` — 获取应用版本（调用主进程）。
- `isDev(): Promise<boolean>` — 是否为开发模式。
- `vectorize(payload): Promise<object>` — 调用后端 `/vectorize` 进行位图→SVG 矢量化。
- `generate(payload): Promise<object>` — 调用后端 `/generate`（或通过主进程转发）生成位图。
- `saveFile(options): Promise<{canceled, filePath}>` — 打开保存对话框并保存单个文件。
- `saveResults(options): Promise<{canceled, filePaths}>` — 选择目录并保存多个产物（png/svg/json 等）。
- `notify(options): Promise<{ok:true}>` — 发送系统通知（如支持）。
- `openExternal(url): Promise<{ok:true}>` — 使用系统默认浏览器打开外部 URL。

## 2. 使用示例

示例：在渲染器中（Vue / plain JS）调用：

```js
// 获取版本
const ver = await window.artTextApp.getAppVersion()

// 生成位图（payload 示例见下）
const resp = await window.artTextApp.generate({ text: '示例', prompt: '霓虹', resolution: '1024 x 1024' })
// resp 约定：{ png: '<data:image/png;base64,...>', image_name: '...', metadata: {...} }

// 矢量化
const vec = await window.artTextApp.vectorize({ image_base64: resp.png, vector: { color_precision: 5, ... } })
// vec 约定：{ svg: '<svg...>', png: '<data:image/png;base64,...>', transparent_png: 'data:...', metadata: {...} }

// 保存所有产物
await window.artTextApp.saveResults({ results: { original: resp.png, svg: vec.svg, metadata: vec.metadata }, fileBase: 'my-art' })
```

## 3. 约定的 Payload / Response（简要）

### `generate(payload)` — 前端到后端 A（生成服务）

请求 payload 常见字段：
- `text` (string) — 艺术字主文本（可选，单条场景）
- `prompt` (string) — 风格提示词
- `negative` (string) — 负面提示
- `resolution` (string) — '1024 x 1024' 等
- `seed` (number) — 随机种子
- `style` (string) — 可选的模型风格

返回示例：
```
{
  png: 'data:image/png;base64,...',
  image_name: 'prompt-1234.png',
  metadata: { model: 'v3', workflow: 'test_z_image_turbo' }
}
```

### `vectorize(payload)` — 前端到后端 B（矢量化服务）

请求 payload 常见字段：
- `image_base64` (string) — data URL（PNG/JPG）或后端生成的 base64
- `image_name` (string) — 可选文件名
- `vector` (object) — 矢量化参数对象，建议包含：
  - `color_precision` (int)
  - `filter_speckle` (int)
  - `corner_threshold` (int)
  - `length_threshold` (int)
  - `layer_difference` (int)
  - `scale` (int)

返回示例：
```
{
  svg: '<svg ...>...</svg>',
  png: 'data:image/png;base64,...',       // 作为预览
  transparent_png: 'data:image/png;base64,...', // 可选透明背景 PNG
  metadata: { quality: { mask_iou: 0.98, contour_chamfer_px: 1.2 }, layers: 6 }
}
```

## 4. 错误与异常

- Electron IPC 调用通过 `ipcRenderer.invoke`，可能抛出 Error。渲染端应捕获并向用户展示友好信息。
- 当在浏览器环境（非桌面）运行时，部分方法不可用（`window.artTextApp` 未定义）。前端应支持回退（例如 `generate` 已在 `src/renderer/api.js` 中实现 HTTP 回退）。

## 5. 版本与兼容性

- 当前文档与 `preload.cjs` 暴露的 `apiVersion: 1.0.0` 对应。若未来扩展/修改接口，请先在 `preload.cjs` 中递增 `apiVersion` 并在此文档中更新说明。

---

