# 03 · 月结／签账读写与汇总预测

Status: resolved

Blocked by: 01

## 任务

用户数据的 CRUD，以及 `GET /rewardcash/summary` 那一组计算。
这是本模块的核心，也是最容易算错的地方。

模块：`backend/app/rewardcash/ledger.py`（月结／签账／设置的存储层）、
`summary.py`（计算）、`api.py` 里的路由。

---

## CRUD

按 issue 01 的表与接口清单实现。三条要点：

- **月结是 `PUT {month}` 幂等 upsert**。用户会反复回来改同一个月（抄错、月中先抄一次）。
  `created_at` 保持首次写入的值，`updated_at` 每次刷新。
- **越权返回 404**，不是 403。与 `rail/api.py` 一致。
- **`earned_json` 写入前校验 key 在当前规则集的 `categories` 白名单里**。
  否则用户抄了个新类别进来，`flow.earned_by_category` 渲染时拿不到 `name` 和 `kind`。
  遇到白名单外的 key → 422，提示「规则集里没有这个类别，请先在控制台加」。

---

## `summary` 的计算

### 顺序

```
1. 读最新规则集 → categories 表、rules 表
2. 读 user_setting → 登记状态、会籍年起算日
3. stock   ← 月结里 month 最大的那一条，直接取，不加总
4. flow    ← 月结按 earned_json 逐 key 加总，范围内的所有月
5. caps    ← 逐条有 cap 的规则算
6. thresholds ← 逐条有 threshold 的规则算
7. projection ← 外推
```

### 3. stock —— 只取最新，不加总

```python
latest = max(entries, key=lambda e: e.month)   # month 是 'YYYY-MM'，字符串比较即可
stock = { "balance": latest.balance, "expiring": {...}, "from_month": latest.month }
```

⚠️ **这是本模块最容易写错的一行。** `balance` / `expiring_amount` 是**快照**，
把 13 个月的余额加起来得到的是一个毫无意义的数，而且看起来很像对的
（13 个月余额之和是个大数，用户会以为自己很有钱）。
`stock` 和 `flow` 在 pydantic 上就是两个不同的模型，别让它们在同一个循环里被处理。

### 5. caps —— 四步短路

对每条 `rule.caps` 非空的规则，按顺序判断，**任一步命中就停**：

```
a. rule.requires_enrolment 且 settings.enrolled[rule.id] 为空
   → derivation = "not_enrolled", used = remaining = null
b. cap.period == "membership_year" 且 settings.membership_year_start 为空
   → derivation = "unavailable", derivation_note = "需先填会籍年起算日"
c. cap.kind == "spend":
     rule.kind 必须 == "rate"
     且 rule.reward_category 非空
     且 categories[rule.reward_category].kind == "rate"
     → used = Σ(窗口内月结的 earned[category]) / rule.rate,  derivation = "rc_backsolve"
     否则 → derivation = "unavailable"
d. cap.kind == "reward":
     used = Σ(窗口内月结的 earned[category])  (RC 本身，不用除)
     category 为空时 → derivation = "unavailable"
```

**`used` 算不出来时置 `null`，绝不置 `0`。** 0 会被前端画成「一点没用」的空进度条，
那是个比「算不出来」危险得多的谎。

### 窗口计算

```
calendar_year    → [as_of 所在年的 01-01, 12-31]
calendar_month   → [as_of 所在月的 1 号, 月末]
promo_period     → [rule.period_start, rule.period_end]
membership_year  → [settings.membership_year_start 起最近一个周年, +1 年 -1 天]
```

⚠️ **不得内联 `"2026-12-31"`。** 历年和本期促销恰好同日结束，
写死现在全对、跨到 2027-01 全错（spec 决策 6）。

月结是按月粒度的，窗口按**月**取交集：`promo_period` 2026-07-01～12-31
对应月份 `2026-07` ~ `2026-12`。窗口起止不在月初月末时（`membership_year` 常见），
按包含关系取整月并在 `derivation_note` 里注明「按整月近似」。

### 6. thresholds —— 只能靠逐笔

```
if 窗口内无 spend_entry:
    derivation = "unavailable", current = null, met = null
else:
    current = Σ amount_hkd where 匹配 threshold.scope（如 region == 'mainland'）
    met = current >= threshold.amount_hkd
    derivation = "spend_entries"
```

月结路径**不参与**门槛计算。理由见 spec 决策 2：月结是次月才抄的，
那时门槛周期已经结束，算出来对预测毫无价值。

### 7. projection —— 只吃 recurring

```
basis = 最近 N 个完整月（N >= 2，不足则 projection = null）
每月 recurring RC = Σ(该月 earned[c]) where c 属于某条 recurrence=="recurring" 的规则
one_off 类别（promo 等）整体剔除，金额记在 excluded_one_off
剩余月数 = as_of 到 window_end 之间的完整月数
projected_additional = recurring_per_month × 剩余月数
```

`window_end` 取**所有 recurring 规则中最早的 `period_end`**（本期是 2026-12-31），
并在 `note` 里写明「促销期结束后归零」。不要外推到促销结束之后——
那是在承诺一笔不存在的收入。

**「当月」不算进基期**：as_of 所在月的月结通常还没抄全，
拿半个月的数当速率会把预测压低。

---

## 验收

用截图那组真实数据（2025-09 ～ 2026-09，共 13 个月，
yc 1299 / card_spend 884 / promo 800 / wellplus 40，余额 3,023）：

- `flow.total == 3023`，四个类别各自对得上。
- `stock.balance == 3023`，`from_month == "2026-09"`。
  **灌满 13 个月后这个数不变**——不是 13 个月余额之和。
- `settings.enrolled["yc-5x"]` 有值时，该 cap `used == 64950`、`remaining == 35050`、
  `derivation == "rc_backsolve"`。
- 清掉 `settings.enrolled["yc-5x"]` → 同一条变成 `derivation == "not_enrolled"`、
  `used == null`。**月结数据没变，但结论必须变。**
- `qr-mobile-2` 和 `dining-3` 因 `reward_category` 为 `null`
  → `derivation == "unavailable"`、`used == null`（issue 02 已知缺口 2）。
- `promo` 800 和 `wellplus` 40 **不出现在任何 cap 的 `used` 里**。
- `travel-guru` 未填 `membership_year_start` → `derivation == "unavailable"`。
- 无 `spend_entry` 时 `thresholds[0].current == null`、`met == null`。
- 灌 3 笔内地签账共 HK$430 → `current == 430`、`remaining == 770`、`met == false`；
  再灌一笔 HK$800 → `met == true`。
- 灌一笔 `region=mainland` 但 `settled_hkd=1` 的签账 → **不计入** `qr-mobile-2` 的条件匹配
  （DCC 陷阱），但仍计入 `dining-3` 的门槛（门槛只看 region 和金额）。
- `projection`：只有 1 个月月结 → `null`；13 个月 → `excluded_one_off == 800`，
  `recurring_per_month` 不含那 800。
- `as_of = 2027-01-05` 时，`yc-5x` 的窗口变成 2027-01-01～12-31、`used` 重新从 0 起算；
  `qr-mobile-2` 因 `period_end` 已过而不再出现在 caps 里。**这条是防内联日期的回归测试。**
- A 用户 token 读 B 的 summary → 只返回 A 自己的数据（不是 404，是空数据）。

## 上线前必办

`GET /rail/export` 和 `DELETE /rail/account` 目前只清乘车记录与身份。
**本模块的三张表必须一并纳入**，否则用户注销后奖赏钱数据留在库里。
`rail/api.py` 里那段跨模块删除顺序的注释要同步更新。

## Comments

- **实现偏差**：存储层没有拆成 `ledger.py`，四张表都在 `rewardcash/store.py` 里。
  规则集的读写和月结的读写共用一个 `_conn()` / `_lock`，拆两个文件只会让同一个库
  有两个入口。计算仍在 `summary.py`。
- **规则数据改了一处**：`yc-5x` 的 `period_start/period_end` 由 `2026-01-01/2026-12-31`
  改为 `null`。这两个字段的语义是「促销窗口，过期即从上限进度里消失」，
  而最红自主奖赏是常设年度项目。原值会让它在 2027-01-01 整条不见——
  用户最主要的赚取规则毫无提示地消失。验收里那条跨年回归现在按预期通过：
  窗口滚到 2027-01-01～12-31、`used` 归 0，而 `qr-mobile-2` 正确地消失。
- **外推口径微调**：`window_end` 仍取最早的促销结束日，但 `note` 不再说「促销期结束后
  归零」——常设规则不会归零，只是那之后的加成是否续期未知、不予预计。
- 验证方式：`pyflakes` 退出 0；另用临时脚本跑通了 13 个月夹具、登记/未登记两态、
  跨年回归、以及 `GET /rail/export` + `DELETE /rail/account` 对本模块三张表的覆盖。
  **没有加进 `scripts/` 的常驻回归**——本仓库无测试框架，这属于人工验证。
