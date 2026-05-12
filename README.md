# 矢量艺术字生成器

这是一个面向“艺术字生成、批量生成、图片矢量化、后端服务和生成工作流”的软件仓库。当前已经整理好的模块是桌面端前端应用。

## 目录结构

```text
art-text-generator/
├─ apps/
│  └─ desktop/            # Electron + Vue 桌面应用
├─ README.md              # 仓库级说明
└─ .gitignore             # 仓库级忽略规则
```

## 后续模块约定

```text
art-text-generator/
├─ apps/
│  └─ desktop/            # 桌面端应用
├─ services/              # 后端服务
├─ workflows/             # 生成工作流、模型流程配置
├─ packages/              # 共享包，例如类型、工具、UI 组件
├─ docs/                  # 产品、接口和开发文档
└─ scripts/               # 构建、部署和开发脚本
```

## 开发入口

桌面应用的开发说明见 `apps/desktop/README.md`。
