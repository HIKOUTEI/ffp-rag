# 02 · 规则数据落地与下发

Status: resolved

Blocked by: 01

## 任务

把 grilling 阶段查到的六条规则做成种子数据，实现下发接口与写入校验。

模块：`backend/app/rewardcash/rules.py`（存储 + 校验）、`api.py` 里的 4 个路由。

---

## 校验（`PUT /rewardcash/admin/rules` 落库前）

整份 JSON 过一遍 pydantic。**校验不过一律 422 且不落库**——
规则集是整份替换的，写进去一份坏数据会让所有用户的 summary 同时算错。

必须拦住的：

| 检查 | 理由 |
|---|---|
| `kind == "rate"` 必须有 `rate` 且 `flat_amount` 为空，反之亦然 | 二者同时有值时反推走哪条没定义 |
| `cap.period` ∈ 四个取值 | 见 spec 决策 6 |
| `cap.period == "promo_period"` 时规则必须有 `period_start` / `period_end` | 否则窗口无从算起 |
| `reward_category` 非空时必须在 `categories` 白名单里 | JSON 存不住外键 |
| `reward_category` 指向的类别 `kind` 必须与规则 `kind` 一致 | 费率规则挂到定额类别上 = 反推出垃圾数字 |
| `threshold.period` ∈ 四个取值 | 同上 |
| `conditions` 里的 `region` / `merchant_category` / `channel` 取值在枚举内 | 逐笔归类靠它 |
| `id` 全集唯一 | |

---

## 种子数据（2026-09-20）

```jsonc
{
  "categories": [
    { "key": "yc",         "name": "最红自主奖赏", "kind": "rate" },
    { "key": "card_spend", "name": "信用卡消费",   "kind": "rate" },
    { "key": "promo",      "name": "优惠",        "kind": "flat" },
    { "key": "wellplus",   "name": "Well+",      "kind": "flat" }
  ],
  "rules": [
    {
      "id": "base-04", "name": "基本奖赏钱",
      "kind": "rate", "rate": 0.004, "recurrence": "recurring",
      "reward_category": "card_spend",
      "caps": [], "threshold": null, "requires_enrolment": false,
      "conditions": {},
      "period_start": null, "period_end": null,
      "status": "official",
      "source": { "url": "https://www.hsbc.com.hk/zh-hk/credit-cards/rewards/terms/", "checked_at": "2026-09-20" },
      "note": "所有付法都有。条款排除的是「购买及／或充值储值卡或电子钱包」这个行为本身，不是「用电子钱包付款」。"
    },
    {
      "id": "yc-5x", "name": "最红自主奖赏（赏世界，额外 5X）",
      "kind": "rate", "rate": 0.02, "recurrence": "recurring",
      "reward_category": "yc",
      "caps": [{ "kind": "spend", "amount": 100000, "period": "calendar_year" }],
      "threshold": null, "requires_enrolment": true,
      "conditions": { "region": ["mainland", "macau", "overseas"] },
      "period_start": "2026-01-01", "period_end": "2026-12-31",
      "status": "official",
      "source": { "url": "https://www.redhotoffers.hsbc.com.hk/tc/rewards/red-hot-rewards-of-your-choice/", "checked_at": "2026-09-20" },
      "note": "类别跟人不跟卡：名下所有汇丰卡共用同一自选类别与同一份 HK$100,000 额度，一年只能年底改一次。要吃满内地 4.4% 必须选「赏世界」。附属卡是否有独立额度未确认（spec 待确认 1）。"
    },
    {
      "id": "qr-mobile-2", "name": "内地／澳门 二维码或流动支付 额外 2%",
      "kind": "rate", "rate": 0.02, "recurrence": "recurring",
      "reward_category": null,
      "caps": [{ "kind": "spend", "amount": 80000, "period": "promo_period" }],
      "threshold": null, "requires_enrolment": false,
      "conditions": {
        "region": ["mainland", "macau"],
        "channel": ["rewardplus_qr", "unionpay_qr", "mobile_pay"],
        "settled_hkd": false
      },
      "period_start": "2026-07-01", "period_end": "2026-12-31",
      "status": "official",
      "source": { "url": "https://www.hsbc.com.hk/content/dam/hsbc/hk/tc/docs/credit-cards/unionpay-dual-currency/diamond-card-terms-and-conditions.pdf", "clause": "DCC_SRP/0726", "checked_at": "2026-09-20" },
      "note": "仅人民币／澳门币结算，按银联国家代码判定。港币结算（DCC）不合资格。「二维码支付」= 汇丰 Reward+ App 或云闪付 App 扫码，仅主卡可用；「流动支付」= Apple/Google/Samsung Pay。支付宝、微信支付明列排除。上限按同一身份证／护照下主卡+附属卡合并。月结单标 \"Mainland China & Macau\"。reward_category 待确认（spec 待确认 2）。"
    },
    {
      "id": "dining-3", "name": "最红签账奖赏 — 中国内地餐饮 额外 3%",
      "kind": "rate", "rate": 0.03, "recurrence": "recurring",
      "reward_category": null,
      "caps": [
        { "kind": "reward", "amount": 80,  "period": "calendar_month" },
        { "kind": "reward", "amount": 480, "period": "promo_period" }
      ],
      "threshold": { "amount_hkd": 1200, "period": "calendar_month", "scope": { "region": "mainland" } },
      "requires_enrolment": true,
      "conditions": { "region": ["mainland"], "merchant_category": ["dining"] },
      "period_start": "2026-07-01", "period_end": "2026-12-31",
      "status": "user_verified",
      "source": { "url": "https://www.redhotoffers.hsbc.com.hk/tc/latest-offers/red-hot-overseas-spending-rewards/", "checked_at": "2026-09-20" },
      "note": "必须先在 Reward+ 登记，登记前的签账不补算。门槛是每历月内地累积合资格签账满 HK$1,200 才触发餐饮加成。美团到店买单按餐饮 MCC 计，实测可拿（故为 user_verified）。注意：最红旅游优惠—美团／大众点评那个 RMB 160 是另一回事，限汇丰 Mastercard 信用卡或扣账卡，Pulse 是银联，不适用。"
    },
    {
      "id": "travel-guru", "name": "Travel Guru 海外实体店额外奖赏",
      "kind": "rate", "rate": 0.06, "recurrence": "recurring",
      "reward_category": null,
      "caps": [{ "kind": "reward", "amount": 2200, "period": "membership_year" }],
      "threshold": null, "requires_enrolment": true,
      "conditions": {
        "region": ["mainland", "macau", "overseas"],
        "channel": ["physical_card", "mobile_pay", "rewardplus_qr", "unionpay_qr", "alipayhk", "wechat"],
        "settled_hkd": false
      },
      "period_start": null, "period_end": null,
      "status": "unavailable",
      "source": { "url": "https://www.redhotoffers.hsbc.com.hk/tc/rewards/travel-guru/", "checked_at": "2026-09-20" },
      "note": "2026 登记窗口未开（历史 2023/9/1–2024/4/7、2024/9/1–10/31、2025/10/1–10/31，历来 9~10 月开），故 unavailable。条款原文是 overseas physical stores \"outside Hong Kong\" + 非港币结算——**内地实体店人民币结算合资格**，不排除内地。2024-09-01 起只限实体店，网上不算。本条按 GURU 级（+6%、2,200 RC）写；GO 是 +3%/600 RC、GING 是 +4%/1,400 RC，窗口开了之后按 user_setting.travel_guru_tier 拆成三条或按 tier 取值。"
    },
    {
      "id": "welcome-2026", "name": "迎新奖赏",
      "kind": "flat", "rate": null, "flat_amount": 800, "recurrence": "one_off",
      "reward_category": "promo",
      "caps": [], "threshold": null, "requires_enrolment": false,
      "conditions": {},
      "period_start": "2026-03-01", "period_end": "2027-02-28",
      "status": "official",
      "source": { "url": "https://www.hsbc.com.hk/content/dam/hsbc/hk/tc/docs/credit-cards/offers/welcome-terms-and-conditions.pdf", "clause": "第 26 条", "checked_at": "2026-09-20" },
      "note": "新客 $800（经官网／网银／App 申请；其他渠道 $600）+ 现金套现分期 $200 = $1,000；旧客 $200。门槛是发卡后首 60 个历日内累积合资格签账 HK$/RMB 8,000（1:1 折算）——**这个周期口径不属于四种之一，故 threshold 置 null，不做进度条**（见下方「已知缺口」）。12 个月内取消过汇丰主卡者无迎新；13 个月内销卡可扣回。排除清单见下。"
    }
  ]
}
```

### 迎新排除清单（`note` 里带不下，单独存在规则的扩展字段或文档里）

年费／财务费用／逾期费 · 附属卡交易 · 邮购传真电话订购 · 经网银缴费 ·
购买／充值储值卡（含经电子钱包增值八达通）· **电子钱包交易含增值，明列 Alipay／WeChat Pay／PayMe** ·
八达通自动增值 · 奖赏钱购物网换购 · 现金贷款与现金套现提款 · 分期供款 ·
半现金交易（外汇／汇票／旅行支票／银行产品）· 电汇／赌博／缴税／自动转账 ·
未志账／取消／退款交易。

---

## 已知缺口（实现时按此处理，别自己发明）

1. **迎新的「发卡后首 60 个历日」不属于四种周期口径**。
   不为它发明第五种 period——本项目场景里迎新是一次性的、用户通常已经过了。
   `threshold` 置 `null`，迎新只作为 `flat` / `one_off` 存在，用途是**在外推时被剔除**。
   若将来真要做迎新进度条，再加 `card_issued_at` 设置和 `card_first_60d` 口径。

2. **`qr-mobile-2` 和 `dining-3` 的 `reward_category` 是 `null`**。
   还不知道这两笔加成在 Reward+ 里落到哪个类别。`null` 的后果是
   **它们的上限进度算不出来**（`derivation: "unavailable"`），这是**正确行为**——
   比猜一个类别然后算出错数字好。用户抄几个月数、对照 Reward+ 的类别名之后回填。

3. **Travel Guru 的三档没展开**。状态是 `unavailable`，展开了也不参与计算。
   窗口开了再说。

---

## 下发

```
GET /rewardcash/rules
  ETag: W/"<version>"
  Cache-Control: no-cache      # 要求每次回源校验，但允许 304
```

`If-None-Match` 命中 → 304 空体。小程序侧据此免流量（见 issue 04）。

## 验收

- 种子数据能过校验并成为 version 1。
- 把 `base-04` 的 `reward_category` 改成 `"promo"`（费率规则挂定额类别）→ 422，不落库。
- 把 `dining-3` 的某个 `cap.period` 改成 `"quarter"` → 422。
- 删掉 `qr-mobile-2` 的 `period_end` 但保留 `promo_period` 上限 → 422。
- 连续 `PUT` 三次，`versions` 列表有 3 条，`GET /rewardcash/rules` 拿到第 3 版。
- `If-None-Match: W/"3"` → 304，体为空。

## Comments
