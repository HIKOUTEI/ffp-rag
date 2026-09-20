# 05 · 控制台：规则维护屏

Status: resolved

Blocked by: 02

## 任务

管理后台加一块「返现规则」。**只维护规则，不碰任何个人数据**（spec 决策 8）。
走已有 `ADMIN_TOKEN`，不需要用户登录。

> 曾计划做「小程序生成配对码 → 网页兑换 token」让控制台也能看个人总览。
> **已砍**：只读总览的边际价值不抵一套登录态的成本。录入场景本来就在手机上。

---

## 形态：带校验的 JSON 编辑器

一个 textarea + 保存按钮 + 版本列表。**不做字段级表单。**

理由：规则 6 条、维护者 1 人、每条规则的 `caps` 是变长数组、
`conditions` 的维度还会随促销换期增减。做成表单要 3 层嵌套动态组件，
而真正的约束全在后端 pydantic 里（issue 02）——表单只会把同一套规则重写一遍，
两边还会漂移。

textarea 的风险是写出坏 JSON，但那个风险已经由后端 422 挡住了：
**校验不过不落库**，`GET /rewardcash/rules` 仍返回旧版本。

### 屏上元素

- **JSON 编辑区**：等宽字体，加载时 `JSON.stringify(data, null, 2)`。
- **保存前本地 `JSON.parse`**，语法错直接在前端报，不必往返一次。
- **备注框**：写「改了什么」，存进 `ruleset.note`。
- **保存**：`PUT /rewardcash/admin/rules`。
  422 时把后端返回的 `detail` **原样显示**，不要包装成「保存失败」——
  pydantic 的报错里有字段路径，那是定位问题的唯一线索。
- **版本列表**：版本号 / 时间 / 备注，只读。点一条能查看那一版的 JSON（只读，不做回滚）。
- **当前版本号**显眼展示，和小程序上报的 `ruleset_version` 对得上就说明下发生效了。

---

## 接进现有代码

按 `frontend/CLAUDE.md`：

- `src/api.ts` 里的 interface 是**手抄** `backend/app/schemas.py` 的，无 codegen、无校验，
  抄错只会在运行时变成 `undefined`。本屏的类型照后端新加的 schema 抄一遍，
  抄完**对着 issue 01 的 JSON 形状逐字段核一遍**。
- 路由前缀 `/rewardcash` 是新的，**必须加进 `vite.config.ts` 的 proxy**，
  否则开发期 404。
- `App.tsx` 是 810 行、~25 个 useState 的单体。**不要顺手重构**——
  照现有区块的写法在后面加一块，风格一致优先于结构优雅。
- lint 用 oxlint（`npm run lint`），`npm run build` 会先跑 `tsc -b`。

---

## 验收

- 贴一份合法规则集 → 保存成功，版本号 +1，版本列表多一条。
- 把 `cap.period` 改成 `"quarter"` → 保存失败，**页面上能看到 pydantic 指出的字段路径**，
  刷新后编辑区仍是旧版本（说明没落库）。
- 故意删一个花括号 → 前端 `JSON.parse` 就拦下，不发请求。
- `npm run build` 通过（`tsc -b` 不报错）。
- `npm run lint` 无新增告警。
- 保存后小程序拉 `/rewardcash/rules` 拿到新 `version`（端到端确认下发链路）。

## Comments

- 改了三个文件，全是净新增（`App.tsx` +147、`api.ts` +115、`vite.config.ts` 的 proxy）。
  `App.tsx` 没有被顺手重构，现有区块一行未动。
- `api.ts` 新增了 `throwWithDetail()`：现有的 `authGet` 只抛 `HTTP 422`，会把 pydantic
  的字段路径吃掉，而那是定位坏规则的唯一线索。后端报错用 `<pre whitespace-pre-wrap>`
  原样渲染，多行不被压成一行。
- `npm run build` 与 `npm run lint` 实跑通过（oxlint 退出 0、零输出）。
- **副作用**：bundle 从 496.08 kB 涨到 500.44 kB，越过 vite 默认的 500 kB 提示线，
  build 仍通过。没有调 `chunkSizeWarningLimit` 去盖掉——真要解决得做代码分割，另开 issue。
- **未验证**：验收清单前三条都要跑起后端才能验（保存成功/版本+1、422 的 detail
  在页面上读起来是否够清楚、小程序端拿到新 version）。目前只做到类型检查 + 静态阅读级别。
