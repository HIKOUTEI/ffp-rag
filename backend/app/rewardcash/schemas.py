"""`/rewardcash` 的请求与响应模型 —— **对外契约的唯一真相**。

与 `app/schemas.py` 分开放，理由同 `rail/schemas.py`：奖赏钱是同服务内的
独立模块，与 RAG 问答没有共享模型。

这里的重头戏是 `RuleSet` 的校验。规则集是**整份替换**的，一份坏数据会让
所有用户的 summary 同时算错，所以写入前必须全量校验、校验不过一律不落库。
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── 枚举 ──────────────────────────────────────────────────────────
# 四种周期口径并存，起止日各不相同。**任何算窗口的代码都必须走这个字段，
# 不得内联日期**——历年与本期促销恰好都在 2026-12-31 结束，写死现在全对、跨年全错。
CapPeriod = Literal["calendar_year", "calendar_month", "promo_period", "membership_year"]
CapKind = Literal["spend", "reward"]
RuleKind = Literal["rate", "flat"]
Recurrence = Literal["recurring", "one_off"]
Confidence = Literal["official", "user_verified", "unverified", "unavailable"]
Region = Literal["mainland", "macau", "hongkong", "overseas"]
MerchantCategory = Literal["dining", "other"]
Channel = Literal["rewardplus_qr", "unionpay_qr", "mobile_pay", "physical_card",
                  "alipayhk", "wechat", "online", "other"]
TravelGuruTier = Literal["go", "ging", "guru"]


# ── 规则集 ────────────────────────────────────────────────────────

class RewardCategory(BaseModel):
    """Reward+ App 自己那套赚取来源分类。

    `kind` 是关键：只有 `rate` 型能由 RC ÷ 费率反推签账额；
    `flat` 型（优惠、Well+）是定额，除以任何费率都是垃圾数字。
    """
    key: str
    name: str
    kind: RuleKind


class Cap(BaseModel):
    kind: CapKind          # spend=限消费额，reward=限拿到的 RC。二者不可混算
    amount: float
    period: CapPeriod


class ThresholdScope(BaseModel):
    region: Optional[Region] = None


class Threshold(BaseModel):
    """触发规则的前置条件，**不是上限**——没到一分不给，到了才开始算。"""
    amount_hkd: float
    period: CapPeriod
    scope: ThresholdScope = Field(default_factory=ThresholdScope)


class Conditions(BaseModel):
    """用于逐笔签账的归类。月结路径不读这里（月结没有地区/付法维度）。"""
    region: Optional[List[Region]] = None
    merchant_category: Optional[List[MerchantCategory]] = None
    channel: Optional[List[Channel]] = None
    settled_hkd: Optional[bool] = None


class RuleSource(BaseModel):
    url: Optional[str] = None
    clause: Optional[str] = None
    checked_at: Optional[str] = None


class Rule(BaseModel):
    id: str
    name: str
    kind: RuleKind
    rate: Optional[float] = None
    flat_amount: Optional[float] = None
    recurrence: Recurrence
    # 对应 Reward+ 的类别 key。**null 表示未知，该规则不参与上限反推**——
    # 这是正确行为，比猜一个类别然后算出错数字好。
    reward_category: Optional[str] = None
    caps: List[Cap] = Field(default_factory=list)
    threshold: Optional[Threshold] = None
    requires_enrolment: bool = False
    conditions: Conditions = Field(default_factory=Conditions)
    period_start: Optional[str] = None      # YYYY-MM-DD
    period_end: Optional[str] = None
    status: Confidence
    source: RuleSource = Field(default_factory=RuleSource)
    note: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "rate":
            if self.rate is None:
                raise ValueError(f"规则 {self.id}：kind=rate 必须填 rate。")
            if self.flat_amount is not None:
                raise ValueError(
                    f"规则 {self.id}：kind=rate 不能同时填 flat_amount"
                    "——两者都有值时反推走哪条没有定义。")
        else:
            if self.flat_amount is None:
                raise ValueError(f"规则 {self.id}：kind=flat 必须填 flat_amount。")
            if self.rate is not None:
                raise ValueError(f"规则 {self.id}：kind=flat 不能同时填 rate。")

        # promo_period 的窗口取自规则自身的起止日，没有就无从算起
        for cap in self.caps:
            if cap.period == "promo_period" and not (self.period_start and self.period_end):
                raise ValueError(
                    f"规则 {self.id}：有 promo_period 上限但缺 period_start/period_end，"
                    "窗口无从算起。")
        if self.threshold and self.threshold.period == "promo_period" \
                and not (self.period_start and self.period_end):
            raise ValueError(
                f"规则 {self.id}：threshold.period=promo_period 但缺 period_start/period_end。")
        return self


class RuleSet(BaseModel):
    categories: List[RewardCategory]
    rules: List[Rule]

    @model_validator(mode="after")
    def _check(self):
        keys = [c.key for c in self.categories]
        if len(keys) != len(set(keys)):
            raise ValueError("categories 的 key 有重复。")
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rules 的 id 有重复。")

        by_key = {c.key: c for c in self.categories}
        for r in self.rules:
            if r.reward_category is None:
                continue
            cat = by_key.get(r.reward_category)
            if cat is None:
                raise ValueError(
                    f"规则 {r.id}：reward_category '{r.reward_category}' 不在 "
                    f"categories 白名单里（JSON 存不住外键，只能在这里挡）。")
            if cat.kind != r.kind:
                raise ValueError(
                    f"规则 {r.id}：kind={r.kind} 却挂到 kind={cat.kind} 的类别 "
                    f"'{cat.key}' 上——费率规则挂定额类别会反推出垃圾数字。")
        return self


class RuleSetPut(BaseModel):
    data: RuleSet
    note: Optional[str] = None


# ── 月结 ──────────────────────────────────────────────────────────

class Expiring(BaseModel):
    amount: Optional[float] = None
    date: Optional[str] = None          # YYYY-MM-DD


class MonthFlow(BaseModel):
    """流量：当月赚取，**可跨月加总**。"""
    earned: Dict[str, float] = Field(default_factory=dict)


class MonthStock(BaseModel):
    """存量：期末快照，**不可加总**，只取最新一条。

    `snapshot_at` 是数据在 Reward+ 上的时点，不等于写库时点——
    用户可能今天补抄上个月的数。

    **日粒度（`YYYY-MM-DD`），不收时间戳。** 它只用来判新鲜度（「该抄这个月的数了」），
    而「这份数属于哪个月」由 `month` 字段承担，小时粒度买不到任何东西，
    只会让各端多一种要处理的格式。
    """
    balance: Optional[float] = None
    expiring: Expiring = Field(default_factory=Expiring)
    snapshot_at: Optional[str] = None       # YYYY-MM-DD


class MonthPut(BaseModel):
    flow: MonthFlow = Field(default_factory=MonthFlow)
    stock: MonthStock = Field(default_factory=MonthStock)


# ── 签账 ──────────────────────────────────────────────────────────

class SpendCreate(BaseModel):
    spend_date: str                      # YYYY-MM-DD
    amount: float
    currency: str = "CNY"
    # 后端不接汇率服务：人民币/澳门币前端按 1:1 预填（迎新条款本身就按 1:1），
    # 其他币种用户自己填。
    amount_hkd: float
    region: Region
    merchant_category: MerchantCategory = "other"
    channel: Channel
    settled_hkd: bool = False            # 被 DCC 成港币结算
    card: Optional[str] = None
    note: Optional[str] = None


class SpendUpdate(BaseModel):
    spend_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    amount_hkd: Optional[float] = None
    region: Optional[Region] = None
    merchant_category: Optional[MerchantCategory] = None
    channel: Optional[Channel] = None
    settled_hkd: Optional[bool] = None
    card: Optional[str] = None
    note: Optional[str] = None


# ── 设置 ──────────────────────────────────────────────────────────

class SettingsPut(BaseModel):
    # {"<rule_id>": "YYYY-MM-DD" | null}。三态：key 不存在=没问过，
    # null=确认未登记，有日期=已登记。别压成布尔两态。
    enrolled: Dict[str, Optional[str]] = Field(default_factory=dict)
    membership_year_start: Optional[str] = None
    travel_guru_tier: Optional[TravelGuruTier] = None
