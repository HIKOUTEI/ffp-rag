"""规则集的种子数据与读写。

规则由后端下发、不随小程序发版（ADR-0009）：内地／澳门扫码 +2% 与内地餐饮 +3%
都在 2026-12-31 到期，Travel Guru 的登记窗口历年 9~10 月开合，
而小程序发版要过微信审核。

⚠️ 规则集是**整份替换**的，一份坏数据会让所有用户的 summary 同时算错。
写入必须走 `validate_and_put`，它先过 `schemas.RuleSet` 再落库。
"""
from app.rewardcash import store
from app.rewardcash.schemas import RuleSet

# 整理日期 2026-09-20。来源：三份官方 T&C PDF + 最红优惠网 + 银联公告。
SEED_RULESET = {
    "categories": [
        {"key": "yc", "name": "最红自主奖赏", "kind": "rate"},
        {"key": "card_spend", "name": "信用卡消费", "kind": "rate"},
        {"key": "promo", "name": "优惠", "kind": "flat"},
        {"key": "wellplus", "name": "Well+", "kind": "flat"},
    ],
    "rules": [
        {
            "id": "base-04",
            "name": "基本奖赏钱",
            "kind": "rate", "rate": 0.004, "recurrence": "recurring",
            "reward_category": "card_spend",
            "caps": [], "threshold": None, "requires_enrolment": False,
            "conditions": {},
            "period_start": None, "period_end": None,
            "status": "official",
            "source": {
                "url": "https://www.hsbc.com.hk/zh-hk/credit-cards/rewards/terms/",
                "checked_at": "2026-09-20",
            },
            "note": "所有付法都有。条款排除的是「购买及／或充值储值卡或电子钱包」"
                    "这个行为本身，不是「用电子钱包付款」。",
        },
        {
            "id": "yc-5x",
            "name": "最红自主奖赏（赏世界，额外 5X）",
            "kind": "rate", "rate": 0.02, "recurrence": "recurring",
            "reward_category": "yc",
            "caps": [{"kind": "spend", "amount": 100000, "period": "calendar_year"}],
            "threshold": None, "requires_enrolment": True,
            "conditions": {"region": ["mainland", "macau", "overseas"]},
            # 刻意留空：`period_*` 是**促销窗口**，过期即从上限进度里消失。
            # 最红自主奖赏是常设的年度项目，额度按历年滚动、每年底重选类别，
            # 不是限时促销。填上 2026-12-31 会让它在 2027-01-01 整条不见——
            # 用户主要的赚取规则毫无提示地消失，比算错还难查。
            # 「条款核对到哪天」由 `source.checked_at` 表达，不要挪用这两个字段。
            "period_start": None, "period_end": None,
            "status": "official",
            "source": {
                "url": "https://www.redhotoffers.hsbc.com.hk/tc/rewards/"
                       "red-hot-rewards-of-your-choice/",
                "checked_at": "2026-09-20",
            },
            "note": "类别跟人不跟卡：名下所有汇丰卡共用同一自选类别与同一份 "
                    "HK$100,000 额度，一年只能年底改一次。要吃满内地 4.4% "
                    "必须选「赏世界」。附属卡是否有独立额度未确认。",
        },
        {
            "id": "qr-mobile-2",
            "name": "内地／澳门 二维码或流动支付 额外 2%",
            "kind": "rate", "rate": 0.02, "recurrence": "recurring",
            # 还不知道这笔加成在 Reward+ 里落到哪个类别 → null，上限进度显示
            # 「算不出来」。这是正确行为，比猜一个类别然后算出错数字好。
            "reward_category": None,
            "caps": [{"kind": "spend", "amount": 80000, "period": "promo_period"}],
            "threshold": None, "requires_enrolment": False,
            "conditions": {
                "region": ["mainland", "macau"],
                "channel": ["rewardplus_qr", "unionpay_qr", "mobile_pay"],
                "settled_hkd": False,
            },
            "period_start": "2026-07-01", "period_end": "2026-12-31",
            "status": "official",
            "source": {
                "url": "https://www.hsbc.com.hk/content/dam/hsbc/hk/tc/docs/"
                       "credit-cards/unionpay-dual-currency/"
                       "diamond-card-terms-and-conditions.pdf",
                "clause": "DCC_SRP/0726",
                "checked_at": "2026-09-20",
            },
            "note": "仅人民币／澳门币结算，按银联国家代码判定。港币结算（DCC）不合资格。"
                    "「二维码支付」= 汇丰 Reward+ App 或云闪付 App 扫码，仅主卡可用；"
                    "「流动支付」= Apple/Google/Samsung Pay。支付宝、微信支付明列排除。"
                    "上限按同一身份证／护照下主卡+附属卡合并。月结单标 "
                    "\"Mainland China & Macau\"。reward_category 待确认。",
        },
        {
            "id": "dining-3",
            "name": "最红签账奖赏 — 中国内地餐饮 额外 3%",
            "kind": "rate", "rate": 0.03, "recurrence": "recurring",
            "reward_category": None,
            "caps": [
                {"kind": "reward", "amount": 80, "period": "calendar_month"},
                {"kind": "reward", "amount": 480, "period": "promo_period"},
            ],
            "threshold": {
                "amount_hkd": 1200,
                "period": "calendar_month",
                "scope": {"region": "mainland"},
            },
            "requires_enrolment": True,
            "conditions": {"region": ["mainland"], "merchant_category": ["dining"]},
            "period_start": "2026-07-01", "period_end": "2026-12-31",
            "status": "user_verified",
            "source": {
                "url": "https://www.redhotoffers.hsbc.com.hk/tc/latest-offers/"
                       "red-hot-overseas-spending-rewards/",
                "checked_at": "2026-09-20",
            },
            "note": "必须先在 Reward+ 登记，登记前的签账不补算。门槛是每历月内地累积"
                    "合资格签账满 HK$1,200 才触发餐饮加成。美团到店买单按餐饮 MCC 计，"
                    "实测可拿（故为 user_verified）。注意：最红旅游优惠—美团／大众点评"
                    "那个 RMB 160 是另一回事，限汇丰 Mastercard 信用卡或扣账卡，"
                    "Pulse 是银联，不适用。",
        },
        {
            "id": "travel-guru",
            "name": "Travel Guru 海外实体店额外奖赏",
            "kind": "rate", "rate": 0.06, "recurrence": "recurring",
            "reward_category": None,
            "caps": [{"kind": "reward", "amount": 2200, "period": "membership_year"}],
            "threshold": None, "requires_enrolment": True,
            "conditions": {
                "region": ["mainland", "macau", "overseas"],
                "channel": ["physical_card", "mobile_pay", "rewardplus_qr",
                            "unionpay_qr", "alipayhk", "wechat"],
                "settled_hkd": False,
            },
            "period_start": None, "period_end": None,
            "status": "unavailable",
            "source": {
                "url": "https://www.redhotoffers.hsbc.com.hk/tc/rewards/travel-guru/",
                "checked_at": "2026-09-20",
            },
            "note": "2026 登记窗口未开（历史 2023/9/1–2024/4/7、2024/9/1–10/31、"
                    "2025/10/1–10/31，历来 9~10 月开），故 unavailable。条款原文是 "
                    "overseas physical stores \"outside Hong Kong\" + 非港币结算"
                    "——内地实体店人民币结算合资格，不排除内地。2024-09-01 起只限"
                    "实体店，网上不算。本条按 GURU 级（+6%、2,200 RC）写；GO 是 "
                    "+3%/600 RC、GING 是 +4%/1,400 RC，窗口开了之后按 "
                    "travel_guru_tier 拆成三条或按 tier 取值。",
        },
        {
            "id": "welcome-2026",
            "name": "迎新奖赏",
            "kind": "flat", "rate": None, "flat_amount": 800, "recurrence": "one_off",
            "reward_category": "promo",
            "caps": [],
            # 门槛是「发卡后首 60 个历日内累积合资格签账 HK$8,000」——这个周期口径
            # 不属于四种之一。**不为它发明第五种**：迎新是一次性的、用户通常已经过了，
            # 它在本模块的唯一用途是「外推时被剔除」。将来真要做进度条，再加
            # card_issued_at 设置和 card_first_60d 口径。
            "threshold": None,
            "requires_enrolment": False,
            "conditions": {},
            "period_start": "2026-03-01", "period_end": "2027-02-28",
            "status": "official",
            "source": {
                "url": "https://www.hsbc.com.hk/content/dam/hsbc/hk/tc/docs/"
                       "credit-cards/offers/welcome-terms-and-conditions.pdf",
                "clause": "第 26 条",
                "checked_at": "2026-09-20",
            },
            "note": "新客 $800（经官网／网银／App 申请；其他渠道 $600）+ 现金套现分期 "
                    "$200 = $1,000；旧客 $200。门槛为发卡后首 60 个历日内累积合资格"
                    "签账 HK$/RMB 8,000（1:1 折算），周期口径特殊故不做进度条。"
                    "12 个月内取消过汇丰主卡者无迎新；13 个月内销卡可扣回。"
                    "不算合资格签账：年费／财务费用／逾期费、附属卡交易、邮购传真电话"
                    "订购、经网银缴费、购买或充值储值卡、电子钱包交易含增值（明列 "
                    "Alipay／WeChat Pay／PayMe）、八达通自动增值、奖赏钱购物网换购、"
                    "现金贷款与现金套现提款、分期供款、半现金交易、电汇／赌博／缴税／"
                    "自动转账、未志账／取消／退款交易。",
        },
    ],
}


def validate(data):
    """过一遍 pydantic。抛 `pydantic.ValidationError`，调用方转 422。"""
    return RuleSet.model_validate(data)


def validate_and_put(data, note=None):
    validate(data)
    return store.put_ruleset(data, note)


def seed_if_empty():
    """库里没有任何版本时写入种子。幂等，可在启动时无脑调用。"""
    version, _ = store.latest_ruleset()
    if version:
        return version
    return validate_and_put(SEED_RULESET, "种子数据（2026-09-20 整理）")


def current():
    """返回 (version, data)。没有版本时自动播种——下发接口不该返回空。"""
    version, data = store.latest_ruleset()
    if not version:
        version = seed_if_empty()
        _, data = store.latest_ruleset()
    return version, data
