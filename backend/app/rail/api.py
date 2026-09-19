"""`/rail` 路由：车次检索、时刻表查询、乘车记录 CRUD、地图数据、导出与注销。

这是「输个车次就自动补全全程停站」的数据出口，录入页的停站列表就靠它。

**不消耗提问额度**：时刻表查询与 RAG 问答无关，走 `rail:` 前缀的独立日额度
（`auth.require_user_with_rail_quota`）；乘车记录的增删改查完全不扣额度。
地图、导出、注销同样不扣——前两者是合规接口，不该被额度拦住。
"""
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException

from app import auth
from app.rail import geo, journey, store
from app.rail.schemas import JourneyCreate, JourneyUpdate

router = APIRouter(prefix="/rail", tags=["rail"])

SEARCH_LIMIT = 20
LIST_LIMIT_MAX = 200


def _require_ready():
    """参考数据没同步过时，明确报「服务未就绪」而不是「车次不存在」。

    两者对用户是完全不同的事：前者要运维去跑同步，后者是他车次输错了。
    """
    if not store.ready():
        raise HTTPException(503, "铁路时刻表尚未同步，请稍后重试。")


def _render_stop(s):
    """库内停站 → 接口停站。做两件事：时刻拆天、坐标转 GCJ-02。"""
    arr, arr_day = store.format_time(s["arrival_min"])
    dep, dep_day = store.format_time(s["departure_min"])
    lat, lon = geo.wgs84_to_gcj02(s["lat"], s["lon"])
    return {
        "seq": s["seq"],
        "station": s["station"],
        "arrival": arr,
        "departure": dep,
        # 跨日车次的 day_offset 最大实测为 3（77:30:00）。前端据此显示「(+2天)」。
        # 取发车日为准：一个停站的到达与发车只可能落在同一天或跨零点，
        # 用发车日标注才与「这趟车开到第几天」一致。
        "day_offset": dep_day if dep is not None else arr_day,
        "dist_km": s["dist_km"],
        "lat": lat,
        "lon": lon,
    }


@router.get("/trains")
def search_trains(q: str = "", authorization: str = Header(None)):
    """车次号前缀检索，供录入时输入联想。`K554` 能搜到 `K551/K554`。"""
    auth.require_user_with_rail_quota(authorization)
    _require_ready()
    return {"trains": store.search_trains(q, SEARCH_LIMIT)}


@router.get("/trains/{number:path}")
def get_timetable(number: str, authorization: str = Header(None)):
    """某车次的完整时刻表。`number` 接受完整车次号或换号别名。

    用 `:path` 而非默认转换器，是因为 **29% 的车次号本身含 `/`**（如 `K551/K554`）。
    默认转换器不匹配斜杠，这些车次会全部 404——而它们恰好是最需要别名解析的那批。
    """
    auth.require_user_with_rail_quota(authorization)
    _require_ready()

    resolved = store.resolve_number(number)
    if not resolved:
        raise HTTPException(404, f"没有找到车次 {number}。")
    train = store.get_train(resolved)
    if not train:
        raise HTTPException(404, f"没有找到车次 {number}。")

    return {
        **train,
        # 录入时记下当前运行图版本，写进乘车记录（issue 06）指向快照（issue 02）
        "gtfs_version": store.get_meta("gtfs_version"),
        "stops": [_render_stop(s) for s in store.get_stops(resolved)],
    }


# ---- 乘车记录 ----
#
# 本项目第一份存在服务端的用户业务数据。所有读写一律带 user_id 条件，
# 越权一律按 404 处理——403 会泄露「这个 id 确实存在」。

def _check_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(422, "乘车日期格式应为 YYYY-MM-DD。")


def _enrich(j, cache):
    """给一条记录回填站名、发到时刻、区段里程。

    车次已不在 `rail.db` 里（停运、改点、或本就是手填的历史车次）时，
    回填 `null` 并标 `stale`，**不报错**——记录的价值不该随车次停运一起消失。
    """
    out = dict(j)
    out["stale"] = False
    out["distance_km"] = None
    out["departure"] = out["arrival"] = None
    out["day_offset"] = None

    if j["source"] == "manual" or j["from_seq"] is None or j["to_seq"] is None:
        return out

    num = j["train_number"]
    if num not in cache:
        cache[num] = {s["seq"]: s for s in store.get_stops(num)}
    stops = cache[num]
    a, b = stops.get(j["from_seq"]), stops.get(j["to_seq"])
    if not a or not b:
        out["stale"] = True
        return out

    out["from_station"] = a["station"]
    out["to_station"] = b["station"]
    if a["dist_km"] is not None and b["dist_km"] is not None:
        out["distance_km"] = round(b["dist_km"] - a["dist_km"], 1)
    # 上车看发车、下车看到达，与票面一致
    out["departure"], dep_day = store.format_time(a["departure_min"])
    out["arrival"], arr_day = store.format_time(b["arrival_min"])
    # 相对上车日的天偏移：跨日车次里「第几天到」是用户真正关心的
    out["day_offset"] = arr_day - dep_day
    return out


@router.post("/journeys")
def create_journey(req: JourneyCreate, authorization: str = Header(None)):
    """新增一条乘车记录。"""
    user_id = auth.require_rail_user(authorization)
    _check_date(req.ride_date)
    if req.source not in ("timetable", "manual"):
        raise HTTPException(422, "source 只能是 timetable 或 manual。")

    f = req.model_dump()
    f["train_number"] = (req.train_number or "").strip().upper()
    if not f["train_number"]:
        raise HTTPException(422, "车次号不能为空。")

    if req.source == "manual":
        # 手填历史：不校验车次存在性，也**不编造时刻**，只留用户自己写的站名。
        if not (req.from_station and req.to_station):
            raise HTTPException(422, "手填记录需填写起讫站名。")
        f["from_seq"] = f["to_seq"] = None
    else:
        _require_ready()
        resolved = store.resolve_number(f["train_number"])
        if not resolved:
            raise HTTPException(422, f"没有找到车次 {req.train_number}。")
        f["train_number"] = resolved
        if req.from_seq is None or req.to_seq is None:
            raise HTTPException(422, "需指定上车站与下车站。")
        if req.from_seq >= req.to_seq:
            raise HTTPException(422, "下车站必须在上车站之后。")
        stops = {s["seq"]: s for s in store.get_stops(resolved)}
        if req.from_seq not in stops or req.to_seq not in stops:
            raise HTTPException(422, "上车站或下车站不在该车次的停站表中。")
        # 站名冗余一份，车次将来停运时记录仍可读
        f["from_station"] = stops[req.from_seq]["station"]
        f["to_station"] = stops[req.to_seq]["station"]
        f["gtfs_version"] = store.get_meta("gtfs_version")

    jid = journey.create(user_id, **f)
    return {"id": jid}


@router.get("/journeys")
def list_journeys(limit: int = 50, offset: int = 0, authorization: str = Header(None)):
    """按乘车日期倒序列出，每条回填站名/时刻/区段里程。"""
    user_id = auth.require_rail_user(authorization)
    limit = max(1, min(limit, LIST_LIMIT_MAX))
    cache = {}
    items = [_enrich(j, cache) for j in journey.list_for(user_id, limit, max(0, offset))]
    return {"journeys": items}


@router.patch("/journeys/{jid}")
def update_journey(jid: str, req: JourneyUpdate, authorization: str = Header(None)):
    user_id = auth.require_rail_user(authorization)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if "ride_date" in fields:
        _check_date(fields["ride_date"])
    if not journey.update(user_id, jid, fields):
        raise HTTPException(404, "记录不存在。")
    return {"ok": True}


@router.delete("/journeys/{jid}")
def delete_journey(jid: str, authorization: str = Header(None)):
    user_id = auth.require_rail_user(authorization)
    if not journey.delete(user_id, jid):
        raise HTTPException(404, "记录不存在。")
    return {"ok": True}


@router.delete("/journeys")
def delete_all_journeys(authorization: str = Header(None)):
    """清空全部记录。个保法要求用户能一键删除自己的数据。"""
    user_id = auth.require_rail_user(authorization)
    return {"deleted": journey.delete_all(user_id)}


@router.get("/stats")
def stats(authorization: str = Header(None)):
    """用户的铁路版图汇总，供「行程」tab 首屏。

    `station_count` 按**去重的途经车站**计——坐 seq 3→9，途中 7 个站都算到过。
    这是打卡语义：车经过了就算走过那条线。
    """
    user_id = auth.require_rail_user(authorization)

    stations, cities, provinces = set(), set(), set()
    class_counts = {}
    total_km = 0.0
    dates = []
    stops_cache, train_cache = {}, {}

    rows = journey.list_for(user_id, limit=100000)
    for j in rows:
        dates.append(j["ride_date"])

        num = j["train_number"]
        if num not in train_cache:
            train_cache[num] = store.get_train(num)
        t = train_cache[num]
        if t and t.get("class"):
            class_counts[t["class"]] = class_counts.get(t["class"], 0) + 1

        if j["source"] == "manual" or j["from_seq"] is None or j["to_seq"] is None:
            # 手填记录没有停站表，只能按用户写的起讫站名回查一次行政区划；
            # 途经站无从得知，不计入。里程同理，跳过（见 spec）。
            for name in (j["from_station"], j["to_station"]):
                if not name:
                    continue
                stations.add(name)
                st = store.get_station(name)
                if st and st["city"]:
                    cities.add(st["city"])
                if st and st["province"]:
                    provinces.add(st["province"])
            continue

        if num not in stops_cache:
            stops_cache[num] = store.get_stops(num)
        seg = [s for s in stops_cache[num] if j["from_seq"] <= s["seq"] <= j["to_seq"]]
        if not seg:
            continue          # 车次已停运/改点，这条算不出，但仍计入 journey_count
        for s in seg:
            stations.add(s["station"])
            if s["city"]:
                cities.add(s["city"])
            if s["province"]:
                provinces.add(s["province"])
        if seg[0]["dist_km"] is not None and seg[-1]["dist_km"] is not None:
            total_km += seg[-1]["dist_km"] - seg[0]["dist_km"]

    return {
        "journey_count": len(rows),
        "total_km": round(total_km, 1),
        "station_count": len(stations),
        # ⚠️ 在 `station.city` / `station.province` 灌数之前，这两个数恒为 0。
        # 灌数需要一份省市边界数据做坐标反查，数据源尚未选定（见 issue 07）。
        "city_count": len(cities),
        "province_count": len(provinces),
        "class_counts": dict(sorted(class_counts.items(), key=lambda kv: -kv[1])),
        "first_ride": min(dates) if dates else None,
        "latest_ride": max(dates) if dates else None,
    }


@router.get("/map")
def map_data(authorization: str = Header(None)):
    """打卡地图页的**唯一**数据来源：所有 leg 的连线点 + 去重车站 + 外接矩形。

    必须一次给全。若让前端按车次逐个调 `/rail/trains/{number}`，一个有 50 条记录的
    用户要发几十次请求，既慢又白耗 `rail:` 日额度——而这里一次都不扣。

    `points` 取 `from_seq..to_seq` 之间的**全部途经站**，与 `/rail/stats` 的
    `station_count` 同一口径（打卡语义：车经过了就算到过）。
    """
    user_id = auth.require_rail_user(authorization)

    legs = []
    # 站名 → {name, lat, lon, count}。站名唯一（`stop_id` 即 `STN_<站名>`），可安全作键。
    stations = {}
    # 按车次缓存停站表，和 `/rail/stats` 里 `stops_cache` 一个写法：
    # 同一车次坐过多次只查一遍库。
    stops_cache = {}

    def tally(name, lat, lon):
        """把一次「到过」计进去重表。坐标传 GCJ-02 转换后的值。"""
        st = stations.get(name)
        if st:
            st["count"] += 1
        else:
            stations[name] = {"name": name, "lat": lat, "lon": lon, "count": 1}

    for j in journey.list_for(user_id, limit=100000):
        if j["source"] == "manual" or j["from_seq"] is None or j["to_seq"] is None:
            # 手填记录没有停站表，画不出连线，**不进 legs**。
            # 但起讫站若在库里查得到，仍应在地图上亮起来——用户确实到过。
            for name in (j["from_station"], j["to_station"]):
                if not name:
                    continue
                st = store.get_station(name)
                if not st:
                    continue
                lat, lon = geo.wgs84_to_gcj02(st["lat"], st["lon"])
                if lat is None or lon is None:
                    continue
                tally(name, lat, lon)
            continue

        num = j["train_number"]
        if num not in stops_cache:
            stops_cache[num] = store.get_stops(num)
        seg = [s for s in stops_cache[num] if j["from_seq"] <= s["seq"] <= j["to_seq"]]
        if not seg:
            continue          # 车次已停运/改点，这条画不出来，跳过而不报错

        points = []
        for s in seg:
            # 小程序 `<map>` 吃的是 GCJ-02，直接给 WGS84 会整体偏移约 550 米，
            # 车站标记落到铁轨旁的居民楼上。`_render_stop` 里是同样的处理。
            lat, lon = geo.wgs84_to_gcj02(s["lat"], s["lon"])
            if lat is None or lon is None:
                continue      # 无坐标的站画不了点，也没法计进 bounds
            points.append({"station": s["station"], "lat": lat, "lon": lon})
            tally(s["station"], lat, lon)
        if not points:
            continue

        legs.append({
            "journey_id": j["id"],
            "train_number": num,
            "ride_date": j["ride_date"],
            "points": points,
        })

    items = list(stations.values())
    lats = [s["lat"] for s in items]
    lons = [s["lon"] for s in items]
    # 无数据时给 null 而不是一个退化的零矩形，让前端自己决定回落到默认视野
    bounds = None if not items else {
        "min_lat": min(lats), "min_lon": min(lons),
        "max_lat": max(lats), "max_lon": max(lons),
    }
    return {"legs": legs, "stations": items, "bounds": bounds}


# 导出时剔除的列：`id`/`user_id` 是内部主键，对用户无意义且没必要外泄；
# `from_seq`/`to_seq` 是 GTFS 停站序号，脱离当期运行图就没有含义——
# 站名已由 `_enrich` 回填，用户要的是「我从哪坐到哪」。
EXPORT_DROP = ("id", "user_id", "from_seq", "to_seq")


@router.get("/export")
def export_data(authorization: str = Header(None)):
    """导出本人全部乘车记录。个保法的「可携带权」，**不扣任何额度**。

    小程序端拿这份 JSON 自己写文件走 `wx.shareFileMessage`，
    故不加附件下载头，`Content-Type` 就是默认的 `application/json`。
    """
    user_id = auth.require_rail_user(authorization)

    cache = {}
    # 导出就是全部，不设 limit（与 `/rail/stats` 同一写法）
    rows = journey.list_for(user_id, limit=100000)
    journeys = []
    for j in rows:
        item = _enrich(j, cache)      # 与 GET /rail/journeys 同一套回填逻辑
        for k in EXPORT_DROP:
            item.pop(k, None)
        journeys.append(item)

    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "journey_count": len(rows),
        "journeys": journeys,
    }


@router.delete("/account")
def delete_account(authorization: str = Header(None)):
    """注销账号：删光乘车记录、身份、内部账号与全部登录 session。

    个保法的「删除权」，必须真删，不是打个标记。路由放在 `rail` 下是因为
    目前只有铁路模块有服务端用户数据；身份/session 那一层交给 `auth.delete_account`。

    **顺序不能反**：先按 user_id 删业务数据，再删身份。反过来的话 user_id
    就查不回来了，乘车记录会成为一堆谁也删不掉的孤儿行。

    ⚠️ 注销后用户再 `wx.login` 拿到的是**同一个 openid**，但 `user_id_of`
    查不到身份会新建一个全新 user_id——旧数据已删且已断开关联，新账号从零开始。
    """
    openid = auth.require_user(authorization)
    # 这里不能用 require_rail_user：它拿的 user_id 和下面要删的身份是同一份，
    # 但注销要的是 openid（session 按 openid 存），两个都得有。
    user_id = auth.user_id_of("wx", openid)
    deleted = journey.delete_all(user_id)
    auth.delete_account(openid)
    return {"deleted_journeys": deleted}
