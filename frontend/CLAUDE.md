# frontend —— 管理后台

React 19 + TypeScript + Vite + Tailwind 3。给我自己用的单页管理控制台，不是面向用户的产品。

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

## 现状：App.tsx 是个 810 行的巨型组件

一个 `App()` 里塞了 ~25 个 `useState`，覆盖 URL 解析、问答、知识体检、知识管理、纠错队列
五块互不相关的功能。**改动时不要顺手重构**，按现有模式在对应区块加代码就行；
`useState` 按功能块分组并留注释分隔（照现有写法）。

真要拆分请单独开一个 `.scratch/` issue 讨论，不要夹带在功能改动里。

## 其他

- lint 用 oxlint（`npm run lint`），不是 ESLint
- 构建 `npm run build` 会先跑 `tsc -b`，类型错误会挡住构建
- `dist/` 未入库（`.gitignore` 忽略），部署时在构建机上现 build
- 无测试
