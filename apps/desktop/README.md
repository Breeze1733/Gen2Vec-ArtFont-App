# 🖥️ @art-text/desktop

基于 Electron + Vue 3 的桌面端应用，提供完整的文生图 → 矢量化本地流水线，并负责后端进程生命周期管理与打包分发。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 主进程 | Electron (`main.cjs`) |
| 渲染进程 | Vue 3 + Vite |
| 预加载桥接 | `preload.cjs` (contextIsolation) |
| 安装包 | electron-builder + NSIS |

---

## 项目结构

```
apps/desktop/
├── electron/
│   ├── main.cjs          # 主进程：窗口管理、后端进程生命周期、文件/通知 IPC
│   ├── preload.cjs       # 预加载脚本：暴露受控 API 到渲染进程
│   └── installer.nsh     # NSIS 自定义脚本：卸载/更新时保留/清理 ComfyUI 引擎
├── src/renderer/
│   ├── main.js           # 渲染进程入口
│   ├── App.vue           # 根组件（输入 / 输出 / 历史 / 验收测试 四面板）
│   ├── components/       # Vue 组件
│   ├── utils/            # 工具函数
│   └── styles/           # 全局样式
├── index.html            # Vite HTML 模板
├── vite.config.js        # Vite 配置（base: './'）
└── package.json
```

---

## 安装依赖

```bash
# 在项目根目录（ apps/desktop 的上两级）
cd apps/desktop
npm install
```

> 依赖 `electron-builder` 会拉取较大二进制文件，首次安装请保持网络通畅。

---

## 开发

### 纯前端热重载（无 Electron）

```bash
npm run dev
```

仅启动 Vite 开发服务器（`http://localhost:5173`），适合调试 UI；不启动任何后端进程。

### 完整桌面开发（含 Electron）

```bash
npm run electron:dev
```

1. 启动 Vite dev server
2. 等待 `localhost:5173` 就绪
3. 启动 Electron 主进程
4. **开发模式下后端不会自动启动**，需手动分别启动两个后端服务（见各自 README）

---

## 构建与打包

```bash
npm run electron:build
```

执行流程：

1. 清理 `../../release`
2. `vite build` —— 打包渲染进程到 `dist/`
3. `electron-builder` —— 打包主进程并生成安装程序

产物位于 `../../release/`：

```
release/
├── 矢量艺术字生成器 Setup 1.0.1.exe   # NSIS 安装包
└── win-unpacked/                      # 绿色版（可直接运行）
```

### 打包内容说明

`electron-builder` 将以下文件作为 `extraResources` 嵌入安装包：

| 来源 | 打包后位置 | 说明 |
|------|-----------|------|
| `services/txt2img-api/dist/txt2img-backend.exe` | `resources/backend/` | 文生图后端 |
| `services/vectorizer-api/dist/vectorizer-backend.exe` | `resources/backend/` | 矢量化后端 |
| `services/vectorizer-api/dist/models` | `resources/backend/models` | 矢量化模型文件 |
| `scripts/download-comfyui-engine.ps1` | `resources/backend/` | ComfyUI 引擎下载脚本 |
| `scripts/download-models.ps1` | `resources/backend/` | 模型下载脚本 |
| `scripts/configure-comfyui.ps1` | `resources/backend/` | ComfyUI 配置脚本 |
| `apps/cli/dist/gen2vec_cli.exe` | `gen2vec_cli.exe` | CLI 工具 |
| `tests/*` | `tests/` | 验收测试脚本与夹具 |

> **安装包大小**：不含 ComfyUI 引擎与模型时约数百 MB；首次运行后自动下载引擎与模型（~30 GB）。

---

## 主进程职责

`electron/main.cjs` 在运行时承担以下职责：

- **窗口管理**：启动闪屏窗口 → 主窗口（Vue 前端）
- **后端进程生命周期**：
  - 打包模式下自动启动 `txt2img-backend.exe` 与 `vectorizer-backend.exe`
  - 应用退出时通过 `/shutdown` 优雅关闭后端
- **首次运行引导**：检测并下载 ComfyUI 引擎与 AI 模型（若用户选择）
- **GPU 优化**：启动前强制使用高性能独立显卡（`--force_high_performance_gpu`）
- **验收测试**：调用打包的 `tests/run-acceptance.bat` 执行端到端测试

---

## 进程间通信 (IPC)

通过 `preload.cjs` 提供的受控 API 与主进程通信：

### 渲染进程 → 主进程（`api.invoke`）

| 通道 | 参数 | 说明 |
|------|------|------|
| `save-file` | `defaultPath`, `content` | 保存文件到磁盘 |
| `open-external` | `url` | 用系统默认浏览器打开链接 |
| `open-directory` | `defaultPath` | 打开目录选择对话框 |
| `get-app-version` | — | 获取应用版本号 |
| `show-notification` | `title`, `body` | 显示系统通知 |
| `accept-pdf` | — | 触发验收测试（生成 PDF 报告） |

### 主进程 → 渲染进程（`events.on` / `progress.on`）

| 通道 | 方向 | 说明 |
|------|------|------|
| `startup-state` | 主 → 渲染 | 启动状态更新（引擎/模型/后端就绪） |
| `startup-error` | 主 → 渲染 | 启动阶段错误通知 |
| `backend-ready` | 主 → 渲染 | 两个后端均就绪 |
| `model-download-progress` | 主 → 渲染 | 模型下载进度（百分比） |
| `model-download-error` | 主 → 渲染 | 模型下载失败 |
| `model-download-done` | 主 → 渲染 | 模型下载完成 |

---

## 安装与卸载行为

`electron/installer.nsh` 自定义了 NSIS 生命周期：

- **全新卸载**：删除 `ComfyUI_windows_portable_nvidia`（~30 GB 运行时下载内容）
- **升级卸载**：将引擎与模型迁移到安装目录同级备份目录，升级完成后自动恢复
- **升级安装**：若检测到备份目录存在，恢复引擎与模型，避免重复下载

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTORIZER_BACKEND_URL` | `http://127.0.0.1:8000/api/v1/vectorize` | 矢量化后端地址 |
| `TXT2IMG_BACKEND_URL` | `http://127.0.0.1:9001/api/v1/txt2img` | 文生图后端地址 |

仅在开发或需要连接外部后端时手动设置。

---

## 相关文档

- [主项目 README](../../README.md) —— 整体架构与快速开始
- [文生图后端](../../services/txt2img-api/README.md) —— `/api/v1/txt2img` 接口定义
- [矢量化后端](../../services/vectorizer-api/README.md) —— `/api/v1/vectorize` 接口定义
