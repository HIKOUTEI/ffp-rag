# frontend —— 控制台

React 19 + TypeScript + Vite + Tailwind 3。给我自己用的单页控制台，不是面向用户的产品。
（叫「控制台 / console」，别叫管理后台，见 `CONTEXT.md` 词条。）

## 部署形态

`base: '/console/'`，生产由 OpenResty 托管在 `ffp.hikoutei.cn/console/`，与 API **同源**。
开发期 Vite 把 `/admin` `/chat` `/health` 代理到 `127.0.0.1:8000`（见 `vite.config.ts`）。

两种情况都不跨域，所以**后端默认不放行任何 CORS 来源**。新增后端路由前缀时，
记得同步加进 `vite.config.ts` 的 `proxy`，否则本地开发 404。

## api.ts 是手写契约

`src/api.ts` 里的 interface 是**手抄** `backend/app/schemas.py` 的，没有任何代码生成或
校验。后端改字段这边不会报错，只会在运行时拿到 `undefined`。改任一侧都要对着另一侧核一遍。

鉴权：admin token 存 localStorage（key `ffp_admin_token`），`post(url, body, auth=true)`
和 `authGet` 自动带 `Authorization`。后端 4xx 的 `detail` 会被抽出来当 `Error.message`。

## 结构：状态全在 App.tsx，分区组件是纯展示

`App.tsx` 是**状态容器**：~30 个 `useState` 和所有 handler 都在这里，按功能块分组
留注释分隔。它渲染 `<Shell>`，按 `section` 挑一个分区组件，用 props 把数据和回调传下去。

```
src/theme.ts       accent 查表（分区主题色）
src/layout/        Shell（侧栏+主区+光晕）、Sidebar、ui（Card/SectionHeader/Stat）
src/sections/      Workbench / Health / Corrections / Manage / Rules
```

**分区组件里不要放 useState**（纯 UI 的开合除外，如抽屉、令牌栏折叠）。状态一旦下沉，
切区就会被卸载——解析到一半去看纠错队列，回来片段就没了。

**accent 类名必须写死在 `theme.ts` 的查表里，不许拼接。** Tailwind 3 只认源码里的
字面量字符串，`` `bg-${accent}-500` `` 会被静默 purge：构建不报错、类型不报错、
运行时颜色直接消失。

加一个分区：`theme.ts` 里加 `SectionId` 与 accent → `Sidebar.tsx` 的 `GROUPS` 加一项
→ 写 `sections/Xxx.tsx` → `App.tsx` 加状态和一个 `{section === 'xxx' && <Xxx .../>}`。

## 其他

- lint 用 oxlint（`npm run lint`），不是 ESLint
- 构建 `npm run build` 会先跑 `tsc -b`，类型错误会挡住构建
- `dist/` 未入库（`.gitignore` 忽略），部署时在构建机上现 build
- 无测试
