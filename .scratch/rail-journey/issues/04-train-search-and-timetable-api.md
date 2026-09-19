# 04 · 车次检索与时刻表查询接口

Status: done

Blocked by: 01, 03

## 任务

`app/rail/api.py`，挂 `/rail` 前缀。这是"自动填写"的核心。

### `GET /rail/trains?q=K551`

车次号模糊检索，供录入时的输入联想。

- 走 `train_number_alias` 表：用户票面上是 `K554`，要能搜到 `K551/K554`。
- 大小写不敏感，`g1` → `G1`。
- 返回 `[{number, class, origin, terminal, stop_count, total_km}]`，限 20 条。
- 空 `q` 返回空数组，不返回全表。

### `GET /rail/trains/{number}`

取某车次的完整时刻表，**这是录入页展开停站列表的数据源**。

返回：

```json
{
  "number": "G1", "class": "高速",
  "origin": "北京南", "terminal": "上海虹桥", "total_km": 1318.0,
  "gtfs_version": "gtfs-20260913-040340",
  "stops": [
    {"seq": 1, "station": "北京南", "arrival": "06:30", "departure": "06:30",
     "day_offset": 0, "dist_km": 0.0, "lat": 39.86494, "lon": 116.37852}
  ]
}
```

要点：

- **时刻渲染**：库里存的是自始发起的总分钟数，可 >1440。
  返回时拆成 `"HH:MM"` + `day_offset`（第几天）。实测最大 `77:30:00` → `day_offset=3`。
  前端可显示成 `02:00 (+2天)`。
- **坐标**：返回 GCJ-02（经 issue 03 转换），直接可喂给 `<map>`。
- `number` 需同时接受完整车次号和别名（`K554` 也能取到 `K551/K554` 的时刻表）。
- 车次不存在返回 404。

### 防刷

这两个接口**不消耗 `DAILY_LIMIT` 提问额度**——它们和 RAG 问答无关，
不该因为记了几趟车就少问几个问题。但要防爬全量时刻表：
按 `user_id` 走独立的日额度（建议 `RAIL_QUERY_DAILY_LIMIT`，默认 500，0 为不限），
复用 `auth._bump()` 的前缀隔离写法（如 `rail:{openid}`）。

## 验收

- `GET /rail/trains?q=K554` 命中 `K551/K554`。
- `GET /rail/trains?q=g1` 命中 `G1`。
- `GET /rail/trains/G1` 返回 7 个停站，末站 `dist_km=1318.0`。
- 某跨日车次的末站 `day_offset >= 1`，时刻字符串不出现 `25:30` 这种非法值。
- 坐标是 GCJ-02（与 `station` 表原值不同）。
- 未登录返回 401；超日额度返回 429 且不影响 `/chat` 额度。

## Comments

### 2026-09-17 实现完成

`backend/app/rail/api.py`（`APIRouter`，`main.py` 里 `include_router`）
+ `store.resolve_number()` / `store.search_trains()` + `config.RAIL_QUERY_DAILY_LIMIT`
+ `auth.require_user_with_rail_quota()`。

`/rail` 用 router 而不是继续往 `main.py` 里堆平铺路由：这个模块最终会有 7+ 个接口，
而 `main.py` 已经 320 行。

验收实跑：

```
q=K554     → K551/K554（新空调快速 / 佳木斯 → 温州 / 50 站 / 3645.0 km）
q=g1       → G1 打头 20 条
GET /rail/trains/G1 → 7 停站，末站 dist_km=1318.0，gtfs_version=gtfs-20260913-040340
K315/K318 末站 重庆西 到 05:30 (+3天) 4022.0km；全程无 HH>23 的非法时刻
北京南 库内 (39.8634831, 116.3723994) → 接口 (39.864866, 116.378617) ✓ 已转 GCJ-02
未登录 401 / 超额 429 / 车次不存在 404 / 库未同步 503
usage 表只出现 rail:openid-a，openid-a 本身无计数 → 未占用提问额度 ✓
```

### 实现中发现并修掉的问题

**含 `/` 的车次号会全部 404。** `@router.get("/trains/{number}")` 的默认路径转换器
不匹配斜杠，而 **29% 的车次号本身就含 `/`**（`K551/K554`）——正是最需要别名解析的那批。
改成 `{number:path}`。实测 `/rail/trains/K551/K554` 与 URL 编码的 `K551%2FK554` 都返回 200。

**LIKE 通配符注入。** `?q=%` 会命中全表。`_like_prefix()` 转义 `%` / `_` / `\`
并带 `ESCAPE '\'`。实测 `?q=%` 返回空数组。

### 两个偏离 spec 的决定

- **库未同步时返回 503，不是 404**。对用户这是两件完全不同的事：
  503 要运维去跑同步，404 是他车次输错了。
- **`day_offset` 取发车日**（无发车时刻则取到达日）。一个停站的到达与发车
  只可能同日或跨零点，用发车日标注才与「这趟车开到第几天」的直觉一致。

### 遗留

检索是**前缀匹配**（`K55` → `K551…`），符合输入联想的语义，也吃得到 `idx_alias` 索引。
代价是用户只记得 `554` 而输 `554` 时搜不到 `K554`。等有真实使用反馈再定要不要加后缀匹配。
