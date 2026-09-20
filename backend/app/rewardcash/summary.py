"""汇总与预测 —— 本模块的核心产出，也是最容易算错的地方。

四项预测各自标明算法来源（`derivation`），**算不出来时一律置 `null`，绝不置 0**。
0 会被前端画成「一点没用」的空进度条，那是个比「算不出来」危险得多的谎。

三个反复出现的陷阱，改这个文件前先读一遍：

1. **存量不可加总**。`stock`（余额、即将到期）只取 month 最大的那条；
   把 13 个月的余额加起来会得到一个看起来很像对的大数。
2. **不得内联日期**。历年与本期促销恰好都在 2026-12-31 结束，
   写死现在全对、跨到 2027-01 全错。窗口一律走 `cap.period`。
3. **定额类别不参与反推**。「优惠」是杂项桶且是定额，除以任何费率都是垃圾数字。
"""
from calendar import monthrange
from datetime import date, timedelta

from app.rewardcash import rules, store

# 外推至少要这么多个完整月做基期。1 个月没有「速率」可言。
MIN_BASIS_MONTHS = 2


# ────────────────────────────── 日期工具 ──────────────────────────────

def _d(s):
    return date.fromisoformat(s)


def _month_of(d):
    return d.strftime("%Y-%m")


def _month_end(d):
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def _add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:      # 2/29
        return d.replace(year=d.year + n, day=28)


def _window(cap_period, rule, as_of, membership_start):
    """算某个上限在 `as_of` 时刻所处的窗口 → (start, end) 或 None（算不出来）。

    ⚠️ 这是「不得内联日期」那条规则的唯一落点。任何别处出现的字面量日期都是 bug。
    """
    if cap_period == "calendar_year":
        return date(as_of.year, 1, 1), date(as_of.year, 12, 31)
    if cap_period == "calendar_month":
        return date(as_of.year, as_of.month, 1), _month_end(as_of)
    if cap_period == "promo_period":
        if not (rule.get("period_start") and rule.get("period_end")):
            return None
        return _d(rule["period_start"]), _d(rule["period_end"])
    if cap_period == "membership_year":
        if not membership_start:
            return None
        start = _d(membership_start)
        # 滚到包含 as_of 的那个周年
        while _add_years(start, 1) <= as_of:
            start = _add_years(start, 1)
        return start, _add_years(start, 1) - timedelta(days=1)
    return None


def _months_in(start, end):
    """窗口覆盖的 'YYYY-MM' 列表。月结是按月粒度的，窗口按**月**取交集。

    起止日不在月初月末时（`membership_year` 常见）按包含关系取整月，
    调用方需在 `derivation_note` 里注明「按整月近似」。
    """
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(_month_of(cur))
        cur = _month_end(cur) + timedelta(days=1)
    return out


def _is_partial_month(start, end):
    return start.day != 1 or end != _month_end(end)


# ───────────────────────────── 各段计算 ─────────────────────────────

def _stock(months):
    """存量：**只取最新，不加总**。

    这是本模块最容易写错的一段。`balance` / `expiring` 是快照——
    13 个月余额之和是个毫无意义却很像对的大数，用户会以为自己很有钱。
    """
    if not months:
        return None
    latest = max(months, key=lambda m: m["month"])
    s = dict(latest["stock"])
    s["from_month"] = latest["month"]
    return s


def _flow(months, categories):
    """流量：按类别跨月加总。"""
    by_key = {c["key"]: c for c in categories}
    totals = {}
    for m in months:
        for k, v in m["flow"]["earned"].items():
            totals[k] = totals.get(k, 0) + (v or 0)
    items = []
    for k, amount in totals.items():
        cat = by_key.get(k)
        items.append({
            "key": k,
            "name": cat["name"] if cat else k,
            "kind": cat["kind"] if cat else None,
            "amount": round(amount, 2),
        })
    items.sort(key=lambda i: -i["amount"])
    ms = sorted(m["month"] for m in months)
    return {
        "range": {"from": ms[0] if ms else None, "to": ms[-1] if ms else None,
                  "months": len(ms)},
        "earned_by_category": items,
        "total": round(sum(i["amount"] for i in items), 2),
    }


def _earned_in(months, window_months, category):
    """窗口内某类别的 RC 合计。"""
    wanted = set(window_months)
    return sum((m["flow"]["earned"].get(category) or 0)
               for m in months if m["month"] in wanted)


def _cap_entry(rule, cap, months, categories, settings, as_of):
    """单条上限的进度。四步短路，任一步命中就停。"""
    by_key = {c["key"]: c for c in categories}
    base = {
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "cap": {"kind": cap["kind"], "amount": cap["amount"], "period": cap["period"]},
        "window": None,
        "used": None,
        "remaining": None,
        "pct": None,
        "derivation": "unavailable",
        "derivation_note": None,
    }

    # a. 未登记优先于一切。用户以为在赚，其实签账一分没在计——
    #    这比显示一个数字重要得多。
    if rule.get("requires_enrolment"):
        enrolled = settings.get("enrolled", {})
        if not enrolled.get(rule["id"]):
            base["derivation"] = "not_enrolled"
            base["derivation_note"] = "未登记，签账不计入。请先在汇丰 Reward+ App 登记。"
            return base

    # b. 窗口算不出来（会籍年缺起算日 / promo 缺起止）
    win = _window(cap["period"], rule, as_of, settings.get("membership_year_start"))
    if win is None:
        base["derivation_note"] = (
            "需先填会籍年起算日。" if cap["period"] == "membership_year"
            else "规则缺 period_start/period_end，窗口无从算起。")
        return base
    start, end = win
    base["window"] = {"start": start.isoformat(), "end": end.isoformat()}

    win_months = _months_in(start, end)
    note = "窗口起止不在月初月末，已按整月近似。" if _is_partial_month(start, end) else None

    cat_key = rule.get("reward_category")
    cat = by_key.get(cat_key) if cat_key else None

    if cat is None:
        base["derivation_note"] = "该规则的奖赏类别未确认，无法从月结反推。"
        return base

    earned = _earned_in(months, win_months, cat_key)

    if cap["kind"] == "spend":
        # c. 签账上限：RC ÷ 费率 反推消费额。仅费率型成立。
        if rule["kind"] != "rate" or cat["kind"] != "rate" or not rule.get("rate"):
            base["derivation_note"] = "定额类别不能反推签账额（除以任何费率都无意义）。"
            return base
        used = earned / rule["rate"]
        base["derivation"] = "rc_backsolve"
        base["derivation_note"] = (
            f"由「{cat['name']}」{round(earned, 2):g} RC ÷ {rule['rate'] * 100:g}% 反推"
            + (f"；{note}" if note else ""))
    else:
        # d. 奖赏上限：直接就是 RC，不用除。
        used = earned
        base["derivation"] = "rc_backsolve"
        base["derivation_note"] = f"「{cat['name']}」窗口内累计 RC" + (f"；{note}" if note else "")

    base["used"] = round(used, 2)
    base["remaining"] = round(max(cap["amount"] - used, 0), 2)
    base["pct"] = round(min(used / cap["amount"], 1.0), 4) if cap["amount"] else None
    return base


def _threshold_entry(rule, spends, as_of):
    """门槛进度。**只能靠逐笔**——月结次月才抄，那时门槛周期已结束。"""
    th = rule["threshold"]
    scope = th.get("scope") or {}
    region = scope.get("region")
    req = (f"本{'历月' if th['period'] == 'calendar_month' else '周期'}"
           f"{'内地' if region == 'mainland' else ''}累计合资格签账 ≥ HK${th['amount_hkd']:,.0f}")

    out = {
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "requirement": req,
        "window": None,
        "current": None,
        "remaining": None,
        "met": None,
        "derivation": "unavailable",
        "derivation_note": None,
    }

    win = _window(th["period"], rule, as_of, None)
    if win is None:
        out["derivation_note"] = "窗口无从算起。"
        return out
    start, end = win
    out["window"] = {"start": start.isoformat(), "end": end.isoformat()}

    in_window = [s for s in spends if start.isoformat() <= s["spend_date"] <= end.isoformat()]
    if not in_window:
        out["derivation_note"] = "还没有逐笔签账记录，记几笔才能算。"
        return out

    total = sum(s["amount_hkd"] for s in in_window
                if region is None or s["region"] == region)
    out["current"] = round(total, 2)
    out["remaining"] = round(max(th["amount_hkd"] - total, 0), 2)
    out["met"] = total >= th["amount_hkd"]
    out["derivation"] = "spend_entries"
    return out


def _projection(months, ruleset, as_of):
    """期末外推。**只吃 recurring**，且不把当月算进基期。

    `window_end` 取所有 recurring 规则中**最早**的 `period_end`——那是赚取速率
    可证明会变的第一个时点，外推过它就是在承诺一笔不存在的收入。
    常设规则（如最红自主奖赏）没有 `period_end`，不参与这个取最小值。
    """
    cats = {c["key"]: c for c in ruleset["categories"]}
    recurring_cats, one_off_cats = set(), set()
    ends = []
    for r in ruleset["rules"]:
        key = r.get("reward_category")
        if key and key in cats:
            (recurring_cats if r["recurrence"] == "recurring" else one_off_cats).add(key)
        if r["recurrence"] == "recurring" and r.get("period_end"):
            ends.append(_d(r["period_end"]))

    # 当月的月结通常还没抄全，拿半个月的数当速率会把预测压低
    cur_month = _month_of(as_of)
    basis = [m for m in months if m["month"] < cur_month]
    if len(basis) < MIN_BASIS_MONTHS:
        return None

    recurring_total = sum(
        (m["flow"]["earned"].get(k) or 0)
        for m in basis for k in recurring_cats)
    one_off_total = sum(
        (m["flow"]["earned"].get(k) or 0)
        for m in basis for k in one_off_cats)

    per_month = recurring_total / len(basis)
    window_end = min(ends) if ends else None
    if window_end is None or window_end <= as_of:
        remaining_months = 0
    else:
        remaining_months = ((window_end.year - as_of.year) * 12
                            + window_end.month - as_of.month)

    return {
        "window_end": window_end.isoformat() if window_end else None,
        "basis_months": len(basis),
        "recurring_per_month": round(per_month, 2),
        "projected_additional": round(per_month * remaining_months, 2),
        "excluded_one_off": round(one_off_total, 2),
        "note": "按现有 recurring 规则的近几月均速外推，算到最早一个促销结束日为止；"
                "此后的加成是否续期未知，不予预计。当月未计入基期。",
    }


# ────────────────────────────── 入口 ──────────────────────────────

def build(user_id, as_of=None):
    as_of = _d(as_of) if as_of else date.today()
    version, ruleset = rules.current()
    months = store.list_months(user_id)
    spends = store.list_spends(user_id, limit=2000)
    settings = store.get_settings(user_id)
    categories = ruleset["categories"]

    caps, thresholds = [], []
    for rule in ruleset["rules"]:
        # 过期规则不出现在进度里——已经结束的促销没有「还剩多少」可言
        if rule.get("period_end") and _d(rule["period_end"]) < as_of:
            continue
        for cap in rule.get("caps") or []:
            caps.append(_cap_entry(rule, cap, months, categories, settings, as_of))
        if rule.get("threshold"):
            thresholds.append(_threshold_entry(rule, spends, as_of))

    return {
        "as_of": as_of.isoformat(),
        "ruleset_version": version,
        "stock": _stock(months),
        "flow": _flow(months, categories),
        "caps": caps,
        "thresholds": thresholds,
        "projection": _projection(months, ruleset, as_of),
    }
