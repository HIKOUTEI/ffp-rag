# 01 · 契约与 schema

Status: resolved

## 任务

定死三张表和一组接口形状。**这是冻结线**——02 / 03 依赖它落地，04 / 05 依赖 02 / 03 跑通。
在本 issue 合并之前，任何一端都不要开始猜字段名。

路由前缀 `/rewardcash`，模块 `backend/app/rewardcash/`（对照 `backend/app/rail/`），
独立 `rewardcash.db` 放在 `DATA_DIR` 下。

> 前置小改动：`main.py` 的 `_require_admin` 提到 `auth.py` 成公开的 `require_admin`，
> `main.py` 改为引用。规则维护接口要用它，不能从 `main` 反向 import（循环依赖）。

---

## 表

### `ruleset` — 规则集，整份 JSON 存一行，append-only 版本

```sql
ruleset(
  version    INTEGER PRIMARY KEY AUTOINCREMENT,
  json       TEXT NOT NULL,      -- 见下方 Rule 定义的数组
  updated_at TEXT NOT NULL,
  note       TEXT                -- 改了什么，给维护者自己看
)
```

**为什么不建规范化的 `rule` 表**：规则一共 6 条，由单个管理员手工维护，
而每条规则的上限是**一到多个**（内地餐饮同时有 $80/历月 和 $480/促销期）、
条件维度还会随促销换期增减。规范化要三张表 + 一套 CRUD 表单，
收益只有「能按字段查」——而这份数据永远是整份读出、整份下发。

整份 JSON + 版本号还顺带解决了下发的缓存问题：`ETag: W/"<version>"`，
小程序带 `If-None-Match` 拿 304。

**代价**：没有字段级约束，必须靠 pydantic 在写入前校验（见 issue 02）。
JSON 存不住外键，`reward_category` 的取值靠校验时对照白名单。

### `monthly_entry` — 月结记录

```sql
monthly_entry(
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  month       TEXT NOT NULL,      -- 'YYYY-MM'
  -- 流量：当月赚取，可跨月加总
  earned_json TEXT NOT NULL,      -- {"<reward_category>": <RC>, ...}
  -- 存量：期末快照，不可加总
  balance     REAL,               -- 期末奖赏钱余额
  expiring_amount REAL,           -- 即将到期 RC
  expiring_date   TEXT,           -- 最近一批的到期日 YYYY-MM-DD
  snapshot_at TEXT,               -- Reward+ 页面上那个「截至」日期，YYYY-MM-DD
  created_at  TEXT, updated_at TEXT
)
UNIQUE(user_id, month)
```

**`earned_json` 为什么不是固定列**：Reward+ 的类别会变（Well+ 就是后加的）。
固定列意味着每加一个类别就要一次迁移。类别的定义权在规则集里，表只存数字。

**`snapshot_at` 不是 `updated_at`**：用户可能今天补抄上个月的数。
**日粒度，不收时间戳**——它只用来判新鲜度，「这份数属于哪个月」由 `month` 承担，
小时粒度买不到任何东西，只会让各端多一种要处理的格式。（实现时定案，2026-09-20）
前者是数据在 Reward+ 上的时点，后者是写库时点，两者不可互相替代。

### `spend_entry` — 签账记录（可选逐笔）

```sql
spend_entry(
  id        TEXT PRIMARY KEY,
  user_id   TEXT NOT NULL,
  spend_date TEXT NOT NULL,       -- YYYY-MM-DD
  amount    REAL NOT NULL,        -- 原币金额
  currency  TEXT NOT NULL,        -- 'CNY' | 'MOP' | 'HKD' | 'OTHER'
  amount_hkd REAL NOT NULL,       -- 折港币。门槛与签账上限一律以港币计
  region    TEXT NOT NULL,        -- 'mainland' | 'macau' | 'hongkong' | 'overseas'
  merchant_category TEXT NOT NULL,-- 'dining' | 'other'
  channel   TEXT NOT NULL,        -- 见下
  settled_hkd INTEGER NOT NULL DEFAULT 0,  -- 是否被 DCC 成港币结算
  card      TEXT,                 -- 可选标卡，'pulse' | 自由文本
  note      TEXT,
  created_at TEXT, updated_at TEXT
)
```

索引：`spend_entry(user_id, spend_date)`。

### `user_setting` — 用户侧的规则状态

```sql
user_setting(
  user_id  TEXT PRIMARY KEY,
  enrolled_json TEXT,           -- {"<rule_id>": "YYYY-MM-DD" | null}，值是登记日期
  membership_year_start TEXT,   -- Travel Guru 会籍年起算日 YYYY-MM-DD
  travel_guru_tier TEXT,        -- 'go' | 'ging' | 'guru' | null
  updated_at TEXT
)
```

**为什么必须有这张表**：最红自主奖赏和内地餐饮 +3% 都 `requires_enrolment`，
而**登记前的签账一分不补算**。不知道用户登记了没，上限进度就没法算——
算出来还会误导（显示「还剩 HK$35,050 可刷」，实际一分没在计）。

`enrolled_json` 存**日期**而不是布尔：登记日决定从哪天开始计入。
值为 `null` 表示「确认未登记」，key 不存在表示「没问过」——三态，别压成两态。

`membership_year_start` 是 `cap.period == "membership_year"` 唯一的起算依据，
未填时该上限标为不可计算。

接口：`GET /rewardcash/settings`、`PUT /rewardcash/settings`（均需 `require_app_user`）。

`channel` 取值：`rewardplus_qr` / `unionpay_qr` / `mobile_pay` / `physical_card` /
`alipayhk` / `wechat` / `online` / `other`。

**`amount_hkd` 为什么是必填而不是算出来的**：后端不接汇率服务（spec「明确不做」）。
人民币／澳门币前端按 1:1 预填（迎新条款本身就按 1:1 算），其他币种用户自己填。

**`settled_hkd` 单独一列而不是塞进 `currency`**：DCC 的语义是
「消费发生在内地、但终端结算成了港币」——`region=mainland` 且 `settled_hkd=1`
是个合法组合，且正是那个「同时丢掉 +2% 和 +6%」的陷阱。
用 `currency='HKD'` 表达会丢掉「这笔发生在内地」的信息。

---

## 规则的 JSON 形状

```jsonc
{
  "id": "dining-3",
  "name": "最红签账奖赏 — 中国内地餐饮",
  "kind": "rate",                 // "rate" | "flat"
  "rate": 0.03,                   // kind=rate 时必填
  "flat_amount": null,            // kind=flat 时必填（RC）
  "recurrence": "recurring",      // "recurring" | "one_off"

  "reward_category": null,        // 对应 Reward+ 的类别 key；null = 未知，不参与反推
  "caps": [
    { "kind": "reward", "amount": 80,  "period": "calendar_month" },
    { "kind": "reward", "amount": 480, "period": "promo_period" }
  ],
  "threshold": {
    "amount_hkd": 1200,
    "period": "calendar_month",
    "scope": { "region": "mainland" }
  },
  "requires_enrolment": true,
  "conditions": {                 // 用于逐笔记录归类；月结路径不读这里
    "region": ["mainland"],
    "merchant_category": ["dining"],
    "settled_hkd": false
  },
  "period_start": "2026-07-01",
  "period_end":   "2026-12-31",
  "status": "official",           // official | user_verified | unverified | unavailable
  "source": {
    "url": "https://www.redhotoffers.hsbc.com.hk/tc/latest-offers/red-hot-overseas-spending-rewards/",
    "clause": "",
    "checked_at": "2026-09-20"
  },
  "note": "美团到店买单按餐饮 MCC 计，实测可拿（user_verified）"
}
```

**`caps` 是数组**，因为一条规则可以同时受多个不同周期的上限约束。

**`cap.period` 取值**：`calendar_year` / `calendar_month` / `promo_period` / `membership_year`。
`promo_period` 的起止取规则自身的 `period_start` / `period_end`；
`calendar_year` 取自然年；`calendar_month` 取自然月；
`membership_year` 需用户在设置里填起算日，未填时该上限标为不可计算。

> ⚠️ 历年和本期促销**都在 2026-12-31 结束**。写死 12-31 现在看全对、跨年全错。
> 任何一处算周期边界的代码都必须走 `cap.period`，不得内联日期。

**奖赏类别白名单**（规则集里同级的一个字段）：

```jsonc
"categories": [
  { "key": "yc",         "name": "最红自主奖赏", "kind": "rate" },
  { "key": "card_spend", "name": "信用卡消费",   "kind": "rate" },
  { "key": "promo",      "name": "优惠",        "kind": "flat" },
  { "key": "wellplus",   "name": "Well+",      "kind": "flat" }
]
```

`kind: flat` 的类别**不参与任何签账额反推**——「优惠」是杂项桶且是定额，
除以任何费率都是垃圾数字（spec 决策 4）。

---

## 接口

### 规则

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| `GET` | `/rewardcash/rules` | 无 | 下发最新规则集，带 `ETag`，支持 `If-None-Match` → 304 |
| `GET` | `/rewardcash/admin/rules` | `ADMIN_TOKEN` | 取当前版本原始 JSON 供编辑 |
| `PUT` | `/rewardcash/admin/rules` | `ADMIN_TOKEN` | 校验后写入新版本，返回新 `version` |
| `GET` | `/rewardcash/admin/rules/versions` | `ADMIN_TOKEN` | 版本列表（版本号 + 时间 + note） |

### 记录（均需 `require_rail_user`，不扣提问额度）

> 函数名沿用 `require_rail_user` 已不准确——它做的是「校验登录取 user_id，不扣额度」，
> 与铁路无关。**本 issue 顺带改名为 `require_app_user`**，`rail/api.py` 的 8 处引用一并改。
> 这是纯改名，不改行为。

| 方法 | 路径 | 说明 |
|---|---|---|
| `PUT` | `/rewardcash/months/{month}` | 新增或覆盖某月月结（幂等 upsert） |
| `GET` | `/rewardcash/months?limit=` | 按月倒序 |
| `DELETE` | `/rewardcash/months/{month}` | 删单月 |
| `POST` | `/rewardcash/spends` | 新增逐笔 |
| `GET` | `/rewardcash/spends?from=&to=` | 按日期倒序 |
| `PATCH` | `/rewardcash/spends/{id}` | 改 |
| `DELETE` | `/rewardcash/spends/{id}` | 删 |
| `GET` | `/rewardcash/summary?as_of=` | **汇总与预测，见下** |

月结用 `PUT {month}` 而非 `POST`：用户会反复回来改同一个月的数（抄错、或月中先抄一次），
幂等覆盖比「先查有没有再决定 POST 还是 PATCH」干净。

### 越权

所有读写带 `user_id` 条件，动别人的记录返回 **404**（不是 403，不泄露该 id 是否存在）。
与 `rail/api.py` 的既有做法一致。

---

## `GET /rewardcash/summary` 的形状

这是整个模块的核心产出，**四项预测各自标明算法来源**。

```jsonc
{
  "as_of": "2026-09-20",
  "ruleset_version": 3,

  // ── 存量：只取 month 最大的那条月结，不加总 ──
  "stock": {
    "balance": 3023,
    "expiring": { "amount": 0, "date": null },
    "snapshot_at": "2026-09-19",
    "from_month": "2026-09"
  },

  // ── 流量：按类别跨月加总 ──
  "flow": {
    "range": { "from": "2025-09", "to": "2026-09", "months": 13 },
    "earned_by_category": [
      { "key": "yc", "name": "最红自主奖赏", "amount": 1299, "kind": "rate" },
      { "key": "card_spend", "name": "信用卡消费", "amount": 884, "kind": "rate" },
      { "key": "promo", "name": "优惠", "amount": 800, "kind": "flat" },
      { "key": "wellplus", "name": "Well+", "amount": 40, "kind": "flat" }
    ],
    "total": 3023
  },

  // ── 预测 1：上限进度 ──
  "caps": [{
    "rule_id": "yc-5x",
    "rule_name": "最红自主奖赏",
    "cap": { "kind": "spend", "amount": 100000, "period": "calendar_year" },
    "window": { "start": "2026-01-01", "end": "2026-12-31" },
    "used": 64950,
    "remaining": 35050,
    "pct": 0.6495,
    "derivation": "rc_backsolve",   // rc_backsolve | spend_entries | not_enrolled | unavailable
    "derivation_note": "由「最红自主奖赏」1,299 RC ÷ 2% 反推"
  }],

  // ── 预测 2：本月门槛 ──
  "thresholds": [{
    "rule_id": "dining-3",
    "rule_name": "最红签账奖赏 — 中国内地餐饮",
    "requirement": "本历月内地累计合资格签账 ≥ HK$1,200",
    "window": { "start": "2026-09-01", "end": "2026-09-30" },
    "current": 430,
    "remaining": 770,
    "met": false,
    "derivation": "spend_entries",
    "derivation_note": null
  }],

  // ── 预测 3：期末外推 ──
  "projection": {
    "window_end": "2026-12-31",
    "basis_months": 3,
    "recurring_per_month": 210.5,
    "projected_additional": 631.5,
    "excluded_one_off": 800,
    "note": "仅按 recurring 规则外推；促销期 2026-12-31 后归零"
  }
}
```

### 三条计算约定

1. **反推**：`used_spend = Σ earned[rule.reward_category] / rule.rate`，
   **仅当** `rule.kind == "rate"` 且 `reward_category` 的 `kind == "rate"` 且该 key 非 null。
   否则 `derivation = "unavailable"`，`used` / `remaining` 置 `null`——
   **不要给 0**，0 会被前端画成「一点没用」的进度条。

2. **门槛只能靠逐笔**。月结是次月才抄的，那时门槛周期已经结束，
   填进去对预测毫无价值（spec 决策 2）。没有逐笔记录时
   `derivation = "unavailable"`、`current = null`，前端显示「记几笔才能算」。

3. **外推只吃 `recurrence == "recurring"`**，且基期至少 2 个完整月，
   不足则 `projection = null`。`excluded_one_off` 要回报，让用户看见迎新那 800 被剔了。

4. **未登记优先于一切**。规则 `requires_enrolment == true` 且 `user_setting.enrolled_json`
   里该 rule_id 的值为 `null` 或缺失时，`derivation = "not_enrolled"`，
   `used` / `remaining` 置 `null`，`derivation_note` 写「未登记，签账不计入」。
   这比显示一个数字重要得多——用户以为在赚，其实一分没有。

---

## 验收

- `GET /rewardcash/rules` 返回 `ETag`；带 `If-None-Match` 重复请求返回 304 空体。
- `PUT /rewardcash/admin/rules` 写一份 `cap.period` 取值非法的 JSON → 422，**不落库**，
  `GET /rewardcash/rules` 仍是旧版本。
- `PUT /rewardcash/months/2026-09` 连发两次，库里只有一条，`updated_at` 变、`created_at` 不变。
- 用截图那组数（yc 1299 / card_spend 884 / promo 800 / wellplus 40）灌入后：
  - `flow.total == 3023`
  - `caps` 里 `yc-5x` 的 `used == 64950`、`remaining == 35050`
  - **`promo` 和 `wellplus` 不出现在任何 `caps` 的 `used` 计算里**
- 灌 13 个月月结后 `stock.balance` 仍是最新那月的值，**不是 13 个月余额之和**。
- 无逐笔记录时 `thresholds[].derivation == "unavailable"` 且 `current == null`（不是 0）。
- `user_setting` 里 `yc-5x` 未登记时，该 cap 的 `derivation == "not_enrolled"`、
  `used == null`，**且不因为月结里有 1,299 RC 就照常反推**。
- 只有 1 个月月结时 `projection == null`。
- A 用户的 token 删 B 的月结 → 404。
- `require_app_user` 改名后 `rail` 的 8 个接口全部照常。

## Comments
