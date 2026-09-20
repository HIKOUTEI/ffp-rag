"""`/rewardcash` 路由：规则下发与维护、月结／逐笔签账 CRUD、设置、汇总预测。

**不消耗提问额度**：奖赏钱记录与 RAG 问答无关，`auth.require_app_user` 只校验登录。
管理接口走 `auth.require_admin`（`ADMIN_TOKEN`）。

越权一律回 **404 而非 403**——403 等于告诉对方「这个 id 确实存在，只是不归你」，
与 `rail/api.py` 的既有做法一致。
"""
import re

from fastapi import APIRouter, Header, HTTPException, Response

from app import auth
from app.rewardcash import rules, store, summary
from app.rewardcash.schemas import (MonthPut, RuleSetPut, SettingsPut,
                                    SpendCreate, SpendUpdate)

router = APIRouter(prefix="/rewardcash", tags=["rewardcash"])

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIST_LIMIT_MAX = 200


def _check_month(month):
    if not MONTH_RE.match(month or ""):
        raise HTTPException(422, "月份格式应为 YYYY-MM，例如 2026-08。")


def _check_date(d, field="日期"):
    if d is not None and not DATE_RE.match(d):
        raise HTTPException(422, f"{field}格式应为 YYYY-MM-DD。")


# ────────────────────────────── 规则 ──────────────────────────────

@router.get("/rules")
def get_rules(response: Response, if_none_match: str = Header(None)):
    """下发最新规则集。**不需登录**——规则是公开知识，小程序首屏就要用。

    带 `ETag`：规则一年改不了几次，而小程序每次冷启动都会拉一遍。
    ETag 取版本号而非内容哈希——版本本来就是单调递增的，比哈希便宜且可读。
    """
    version, data = rules.current()
    etag = f'W/"rc-{version}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return {"version": version, "ruleset": data}


@router.get("/admin/rules")
def admin_get_rules(version: int = None, authorization: str = Header(None)):
    """取规则集原始 JSON 供控制台编辑。`version` 缺省取最新。"""
    auth.require_admin(authorization)
    if version is not None:
        data = store.get_ruleset_version(version)
        if data is None:
            raise HTTPException(404, f"没有第 {version} 版规则集。")
        return {"version": version, "ruleset": data}
    cur, data = rules.current()
    return {"version": cur, "ruleset": data}


@router.put("/admin/rules")
def admin_put_rules(req: RuleSetPut, authorization: str = Header(None)):
    """整份替换。校验不过一律不落库——一份坏数据会让所有用户同时算错。"""
    auth.require_admin(authorization)
    try:
        version = rules.validate_and_put(req.data.model_dump(), req.note)
    except ValueError as e:
        raise HTTPException(422, f"规则集校验不通过：{e}")
    return {"version": version}


@router.get("/admin/rules/versions")
def admin_rule_versions(limit: int = 50, authorization: str = Header(None)):
    auth.require_admin(authorization)
    return {"versions": store.list_ruleset_versions(max(1, min(limit, LIST_LIMIT_MAX)))}


# ───────────────────────────── 月结记录 ─────────────────────────────

@router.put("/months/{month}")
def put_month(month: str, req: MonthPut, authorization: str = Header(None)):
    """新增或覆盖某月月结（幂等）。用 PUT 不用 POST：用户会反复回来改同一个月。"""
    user_id = auth.require_app_user(authorization)
    _check_month(month)
    _check_date(req.stock.snapshot_at, "快照日期")
    _check_date(req.stock.expiring.date, "到期日期")

    version, ruleset = rules.current()
    known = {c["key"] for c in ruleset["categories"]}
    unknown = [k for k in req.flow.earned if k not in known]
    if unknown:
        # 挡在这里而不是静默收下：类别 key 写错的话那笔 RC 永远不会进任何汇总，
        # 用户看到的是「记了但没算」，比报错难查得多。
        raise HTTPException(
            422, f"未知的奖赏类别：{'、'.join(unknown)}（规则集第 {version} 版）。")

    entry = store.put_month(
        user_id, month, req.flow.earned,
        balance=req.stock.balance,
        expiring_amount=req.stock.expiring.amount,
        expiring_date=req.stock.expiring.date,
        snapshot_at=req.stock.snapshot_at,
    )
    return entry


@router.get("/months")
def list_months(limit: int = 60, authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    return {"months": store.list_months(user_id, max(1, min(limit, LIST_LIMIT_MAX)))}


@router.delete("/months/{month}")
def delete_month(month: str, authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    _check_month(month)
    if not store.delete_month(user_id, month):
        raise HTTPException(404, "该月没有记录。")
    return {"ok": True}


# ───────────────────────────── 签账记录 ─────────────────────────────

@router.post("/spends")
def create_spend(req: SpendCreate, authorization: str = Header(None)):
    """新增逐笔。它唯一不可替代的用途是月中推算门槛进度。"""
    user_id = auth.require_app_user(authorization)
    _check_date(req.spend_date, "签账日期")
    if req.amount_hkd < 0:
        raise HTTPException(422, "港币金额不能为负。")
    return {"id": store.create_spend(user_id, **req.model_dump())}


@router.get("/spends")
def list_spends(date_from: str = None, date_to: str = None, limit: int = 200,
                authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    _check_date(date_from, "起始日期")
    _check_date(date_to, "结束日期")
    spends = store.list_spends(user_id, date_from, date_to,
                               max(1, min(limit, LIST_LIMIT_MAX)))
    return {"spends": spends}


@router.patch("/spends/{sid}")
def update_spend(sid: str, req: SpendUpdate, authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    _check_date(fields.get("spend_date"), "签账日期")
    if "settled_hkd" in fields:
        fields["settled_hkd"] = int(fields["settled_hkd"])
    if not store.update_spend(user_id, sid, fields):
        raise HTTPException(404, "记录不存在。")
    return {"ok": True}


@router.delete("/spends/{sid}")
def delete_spend(sid: str, authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    if not store.delete_spend(user_id, sid):
        raise HTTPException(404, "记录不存在。")
    return {"ok": True}


# ────────────────────────────── 设置 ──────────────────────────────

@router.get("/settings")
def get_settings(authorization: str = Header(None)):
    user_id = auth.require_app_user(authorization)
    return store.get_settings(user_id)


@router.put("/settings")
def put_settings(req: SettingsPut, authorization: str = Header(None)):
    """整份覆盖。`enrolled` 是三态字典，客户端须回传完整的那一份。"""
    user_id = auth.require_app_user(authorization)
    _check_date(req.membership_year_start, "会籍年起算日")
    for rule_id, d in req.enrolled.items():
        _check_date(d, f"规则 {rule_id} 的登记日期")
    return store.put_settings(user_id, req.enrolled,
                              req.membership_year_start, req.travel_guru_tier)


# ────────────────────────── 汇总与预测 ──────────────────────────

@router.get("/summary")
def get_summary(as_of: str = None, authorization: str = Header(None)):
    """四项预测：上限进度、门槛进度、期末外推、即将到期。

    `as_of` 只为调试与回归（跨年那条必测），线上客户端不传。
    """
    user_id = auth.require_app_user(authorization)
    _check_date(as_of, "as_of")
    return summary.build(user_id, as_of)


# ────────────────────────────── 数据清理 ──────────────────────────────

@router.delete("/data")
def delete_data(authorization: str = Header(None)):
    """清空本人在奖赏钱模块的全部数据，但**保留账号**。

    与注销（`DELETE /rail/account`）不同：那个是销号，这个只是清账本重来。
    导出没有本模块专属入口——`GET /rail/export` 是整个账号的导出口，
    再开一个只会让客户端有机会只导一半（ADR-0010）。
    """
    user_id = auth.require_app_user(authorization)
    return store.delete_all_for(user_id)
