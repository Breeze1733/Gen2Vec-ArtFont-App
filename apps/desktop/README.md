# 桌面端应用

这是基于 Vue 3、Vite 和 Electron 的桌面端前端应用，用于开发“艺术字生成 / 批量生成 / 图片矢量化”的本地工具界面。

## 目录结构

```text
apps/desktop/
├─ electron/              # Electron 主进程与预加载脚本
│  ├─ main.cjs
│  └─ preload.cjs
├─ src/
│  └─ renderer/           # 前端渲染进程源码
│     ├─ styles/          # 全局样式
│     │  └─ global.css
│     ├─ App.vue          # 应用主界面
│     └─ main.js          # Vue 入口
├─ index.html             # Vite HTML 入口
├─ package.json           # 脚本、依赖和 Electron 打包配置
├─ package-lock.json      # npm 锁定文件
└─ vite.config.js         # Vite 配置
```

## 开发命令

```bash
npm install
npm run dev
npm run electron:dev
npm run build
npm run electron:build
```

## 规范约定

- `electron` 只放桌面端壳层相关代码。
- `src/renderer` 只放前端渲染进程源码。
- 全局样式放在 `src/renderer/styles`。
- 后续图片等静态资源统一放在 `src/renderer/assets`。
