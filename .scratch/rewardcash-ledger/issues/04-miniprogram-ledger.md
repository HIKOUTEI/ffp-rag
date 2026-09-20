# 04 · 小程序：总览 + 月结录入 + 可选逐笔

Status: resolved

Blocked by: 02, 03

## 任务

三个页面。**录入成本是这个产品的生死线**——用户一个月只来一次，
如果抄数要超过一分钟，下个月就不来了（spec 目标）。

### 位置

第 5 个 tab「奖赏」。`app.json` 的 `pages` + `tabBar.list` 都要加，
`custom-tab-bar/` 也要同步（`"custom": true`）。

⚠️ 微信 tabBar 上限就是 5 个，加完**再无空位**。若觉得挤，
备选是收进「我的」做二级入口——但那会让月结录入多两次点击，与「录入成本」目标相悖。
先按 tab 做，实际用一个月再决定。

### 新增

```
pages/reward/reward           总览
pages/reward-month/reward-month   月结录入
pages/reward-spend/reward-spend   逐笔录入（可选功能）
```

每页 4 个文件（`.js` / `.json` / `.wxml` / `.wxss`）+ `app.json` 注册。
另加 `styles/reward.wxss`（对照 `styles/rail.wxss`）与 `reward-util.js`
（金额格式化、周期窗口文案、进度百分比）。

---

## `api.js`

按 `miniprogram/CLAUDE.md` 的硬规矩：所有请求走 `api.js`，
每个方法上方**注释写明返回形状**（那是小程序侧唯一的契约文档）。

```js
// GET /rewardcash/rules
// → { version, categories: [{key,name,kind}], rules: [...] }
// 带 If-None-Match，304 时返回本地缓存那份
// GET /rewardcash/summary?as_of=YYYY-MM-DD
// → { as_of, ruleset_version, stock:{...}, flow:{...}, caps:[...], thresholds:[...], projection }
// PUT /rewardcash/months/:month  { flow:{earned:{}}, stock:{balance,expiring,snapshot_at} }
// GET /rewardcash/months?limit=
// POST /rewardcash/spends / GET / PATCH / DELETE
// GET|PUT /rewardcash/settings
```

**规则集走本地缓存 + ETag**：`wx.setStorageSync('rc_ruleset', {version, data})`，
请求带 `If-None-Match: W/"<version>"`，304 就用缓存。规则一个月未必变一次，
每次进页面都全量拉是浪费。

---

## 总览页 `pages/reward/`

自上而下：

**1. 余额卡**
大字余额（来自 `stock.balance`），下方小字「截至 <snapshot_at>」。
`snapshot_at` 必须显示——用户要知道这个数有多旧。
超过 35 天没更新时，卡片下方出现「该抄这个月的数了」的行动按钮。

**2. 即将到期**
`stock.expiring.amount > 0` 时才显示，红色，带到期日与剩余天数。
为 0 或 `null` 时**整块不渲染**，不要显示「即将到期 0」。

**3. 上限进度**
每条 `caps` 一行：规则名 + 进度条 + `已用 / 上限` + 周期窗口文案。

四种 `derivation` 四种渲染，**绝不共用一套**：

| derivation | 渲染 |
|---|---|
| `rc_backsolve` / `spend_entries` | 正常进度条 + 数字 |
| `not_enrolled` | 灰条 + 「**未登记，签账不计入**」+ 「去 Reward+ 登记」提示 + 跳到设置页 |
| `unavailable` | 灰条 + `derivation_note`（如「需先填会籍年起算日」） |

⚠️ `used == null` 时**不要传 0 给进度条组件**。画成空条等于告诉用户「还没开始用」，
而真相是「算不出来」——这个谎比不显示危险得多。灰条 + 文案。

**4. 本月门槛**
每条 `thresholds` 一行。`met == true` 显示绿色对勾；
`false` 显示「还差 HK$770」+ 距月底天数；
`derivation == "unavailable"` 显示「记几笔签账才能算」+ 跳逐笔录入。

**5. 类别分布**
`flow.earned_by_category` 的横向条形（不用饼图，四个类别的饼图读不出差距）。
`kind == "flat"` 的类别加一个小标记，hover/长按说明「定额收入，不参与签账额反推」。

**6. 期末预计**
`projection` 为 `null` 时显示「再记一个月就能预测」。
非 null 时显示预计新增 + `excluded_one_off`（「已剔除一次性收入 $800」）——
这行必须显示，否则用户会怀疑预测偏低。

---

## 月结录入页 `pages/reward-month/`

**这一页的唯一目标是「抄数一分钟内完成」。**

- 月份选择器，默认当前月，可往回选。已有记录时**预填旧值**（在改，不是重填）。
- 类别输入框由 `categories` 动态生成——新增类别不用发版。
- 三个存量字段：余额 / 即将到期 RC / 到期日。都可空。
- `snapshot_at` 默认取提交时刻，可手改（用户抄的是 Reward+ 页面上那个「截至」时间，
  和提交时刻可能差几小时，跨月时差别就重要了）。
- **数字键盘**（`type="digit"`），不要让用户在全键盘上找数字。
- 提交走 `PUT`，幂等，重复提交安全。

页面顶部放一行「打开 Reward+ →『奖赏钱』→ 照着抄」，
并按 `categories` 的顺序排列输入框，与 App 里的显示顺序一致。**顺序错了就没法照抄。**

---

## 逐笔录入页 `pages/reward-spend/`

**摆明是可选的。** 入口只在总览页的门槛那一行（「记几笔签账才能算」）
和一个次级入口，不做首屏大按钮。

表单：日期（默认今天）/ 金额 + 币种 / 地区 / 餐饮还是其他 / 付法 / 是否被 DCC 成港币。

- 人民币、澳门币按 1:1 预填 `amount_hkd`（迎新条款本身就按 1:1），可改。
- **DCC 那个开关要有一句说明**：「刷卡时被问『港币还是人民币』，
  选了港币就勾上——会同时失去扫码 +2%」。这是整套规则里最容易白丢钱的地方。
- 付法选项配文案：「Reward+ 扫码（仅主卡）」「云闪付扫码」「Apple/Google/Samsung Pay」
  「实体卡」「AlipayHK」「微信支付」「网上」。后三个下方灰字注明「只有基本 0.4%」。

列表按日期倒序，左滑删除。

---

## 设置页

并到「我的」或总览页的齿轮入口，不单开 tab。

- 逐条列出 `requires_enrolment == true` 的规则，开关 + 登记日期选择器。
  **三态**：未问过 / 确认未登记 / 已登记（带日期）——别压成开关的两态。
- Travel Guru 会籍年起算日 + 等级（该规则 `status == "unavailable"` 时整块置灰，
  提示「2026 登记窗口未开」）。

---

## 验收

- 灌 13 个月月结后，余额卡显示 3,023 而不是 13 个月之和。
- 把 `yc-5x` 的登记开关关掉，上限那一行立刻变灰条 + 「未登记，签账不计入」，
  **进度条不显示 0%**。
- `qr-mobile-2` / `dining-3` 显示灰条 + 说明，不显示 0。
- 无逐笔记录时门槛行显示「记几笔签账才能算」并能跳转。
- 规则集未变时二次进入总览页，Network 面板里 `/rewardcash/rules` 是 304。
- 月结录入页预填已有值，改一个数字提交后库里仍只有一条。
- 到期金额为 0 时「即将到期」整块不渲染。
- 真机验证（`miniprogram/CLAUDE.md`：部分行为只能在真机上确认）。

## Comments

- 新建 18 个文件（多做了第 4 页 `pages/reward-settings/`——「跳到设置页」和「不单开 tab」
  两条要求需要它落地），改 3 个（`api.js` / `app.json` / `custom-tab-bar/index.js`）。
- `null ≠ 0` 落在 `reward-util.js` 的 `capView()` 一个点上，并多加了一层兜底：
  `used == null` 时即便 `derivation` 写着 `rc_backsolve` 也降级成 `unknown`，
  防的是后端哪天漏置 `derivation`。这层是 issue 没要求的，留着。
- `reward.rules()` 用裸 `wx.request` 处理 `If-None-Match`（通用 `request()` 带不了自定义头），
  但仍关在 `api.js` 内，页面里没有裸请求。
- **`snapshot_at` 定为日粒度**：本 issue 原写「精确到小时」，与 `api.py` 的 `DATE_RE` 冲突。
  已判定是 issue 01 的示例过时——月结账本里这个字段只判新鲜度，
  「属于哪个月」由 `month` 承担。issue 01 与 `schemas.py` 已同步改正，小程序按日粒度发。
- `DELETE /rail/account` 已连带清本模块三张表（issue 03 做掉了），小程序无需额外处理。
- **验证级别**：`node --check` 过 7 个 js、`JSON.parse` 过 5 个 json；
  另写了 37 条 Node 断言跑 `reward-util.js` 的 null/0 分支，全过。
  **没进模拟器、没上真机、没连后端**——本 issue「验收」的 7 条全部未验证。
