# 11 · 地图数据接口 + 数据导出 + 注销账号

Status: done

Blocked by: 06, 07

负责目录：**只改 `backend/app/rail/` 与 `backend/app/auth.py`**。
不要动 `miniprogram/` 下的任何文件——那三个页面由并行的其他任务负责。

## 背景

前两项（导出、注销）是 spec「上线前必办」里点名的**个保法要求**，不是可选功能。
删除单条与清空全部已在 issue 06 实现，缺的是**导出**与**注销账号**。
第一项（`GET /rail/map`）是打卡地图页（issue 10）的唯一数据来源。

## 1. `GET /rail/map`

地图页一次拿全。**必须一次请求拿完**：若让前端按车次逐个调 `/rail/trains/{number}`，
一个有 50 条记录的用户要发几十次请求，既慢又白耗 `rail:` 日额度。

```json
{
  "legs": [
    { "journey_id": "a1b2c3d4", "train_number": "G1", "ride_date": "2026-09-14",
      "points": [ {"station": "北京南", "lat": 39.86, "lon": 116.38}, … ] }
  ],
  "stations": [ {"name": "北京南", "lat": 39.86, "lon": 116.38, "count": 3} ],
  "bounds": {"min_lat": …, "min_lon": …, "max_lat": …, "max_lon": …}
}
```

- 鉴权走 `auth.require_rail_user`，**不扣 `rail:` 额度**（和 `/rail/journeys` 一致，
  只有 `/rail/trains*` 才扣）。
- `points` = 该记录 `from_seq..to_seq` 之间的**全部途经站**，按 seq 升序。
  这与 `/rail/stats` 里 `station_count` 的口径一致（打卡语义：经过即到过）。
- **坐标必须过 `geo.wgs84_to_gcj02`**——小程序 `<map>` 用 GCJ-02，
  直接给 WGS84 会整体偏移约 550m。`_render_stop` 里已有同样的处理，照做。
- `stations` 去重按站名，`count` 为该站在所有 legs 中出现的次数。
- 手填记录（`source == 'manual'`）**不进 `legs`**（没有停站表）；
  但其 `from_station` / `to_station` 若能 `store.get_station(name)` 查到，
  则计入 `stations`（`count` 各 +1）。
- 车次已停运/改点（`get_stops` 查不到该 seq 区间）的记录直接跳过，**不报错**。
- 无数据时 `legs`/`stations` 为 `[]`，`bounds` 为 `null`。
- **`legs` 按 `ride_date` 倒序**（与 `GET /rail/journeys` 同序）。这是接口保证，
  不是实现巧合——补记于 2026-09-17，实现时已经是这个行为。
- 性能：按 `train_number` 做 per-request 缓存，和 `/rail/stats` 里 `stops_cache` 一个写法。

## 2. `GET /rail/export`

用户把自己的数据带走。返回完整 JSON，前端写成文件走 `wx.shareFileMessage`。

```json
{
  "exported_at": "2026-09-17T14:03:11",
  "journey_count": 42,
  "journeys": [
    { "train_number": "G1", "ride_date": "2026-09-14",
      "from_station": "北京南", "to_station": "上海虹桥",
      "departure": "06:30", "arrival": "11:24", "day_offset": 0,
      "distance_km": 1318.0, "note": "", "source": "timetable",
      "gtfs_version": "2026-09-13", "created_at": "…" }
  ]
}
```

- 用 `_enrich` 回填，和 `GET /rail/journeys` 同一套逻辑，**不要重写一遍**。
- 不设 limit，导出就是全部（用 `journey.list_for(user_id, limit=100000)`，
  和 `/rail/stats` 一样）。
- **不要导出 `user_id` 和内部 `id`**——对用户无意义，且 `user_id` 是内部主键，
  没必要外泄。`from_seq`/`to_seq` 同理，去掉。
- `Content-Type` 就用默认的 `application/json`，不做附件下载头——
  小程序端是自己写文件的，不走浏览器下载。

## 3. `DELETE /rail/account`

注销账号。个保法的「删除权」，必须真删。

- 删除该 `user_id` 的全部乘车记录（`journey.delete_all`）。
- 删除 `identity` 表里指向该 `user_id` 的行，以及 `user` 表里那一行。
- 删除该 openid 的全部登录 session（`auth` 里 session 表），使 token 立即失效。
- 返回 `{"deleted_journeys": n}`。
- ⚠️ **幂等**：重复调用不报错，第二次返回 `{"deleted_journeys": 0}`。
- ⚠️ 注销后用户再次 `wx.login` 会拿到**同一个 openid**，
  于是 `user_id_of('wx', openid)` 会**新建一个全新的 `user_id`**——
  这正是我们要的：旧数据已断开关联且已删除，新账号从零开始。
  实现时务必确认 `user_id_of` 走的是「查不到就新建」而不是缓存旧值。
- 这个接口跨了 `rail` 与 `auth` 两块，把删身份/session 的部分写成
  `auth.py` 里的一个函数（如 `delete_account(openid)`），`rail/api.py` 调它。
  路由本身放 `rail/api.py`，因为目前只有铁路模块有服务端用户数据。

## 4. 日额度

`RAIL_QUERY_DAILY_LIMIT`（默认 500）只作用于 `/rail/trains*`。
本 issue 新增的三个接口都**只用 `require_rail_user`，不扣额度**。
导出和注销是合规接口，不该被额度拦住。

## 验收（用 curl 或 pytest 实跑，把输出贴到 Comments 里）

- 建 2 条时刻表记录 + 1 条手填记录，`GET /rail/map`：
  `legs` 有 2 条、`points` 数量等于各自区段站数、`stations` 里包含手填那两个站名。
- 坐标验证：北京南在 `legs[0].points[0]`，`lat` 约 39.86 且**与库里 WGS84 原值不同**
  （证明确实转过 GCJ-02）。
- `GET /rail/export` 的 `journey_count` 与 `/rail/stats` 的一致，
  且响应里不含 `user_id`、`id`、`from_seq`、`to_seq`。
- `DELETE /rail/account` 后：`GET /rail/journeys` 用旧 token 返回 401；
  重新登录后 `GET /rail/stats` 全 0。
- 连续两次 `DELETE /rail/account` 不报 500。
  （**措辞修正 2026-09-17**：session 已被删光，拿旧 token 的第二次调用根本过不了鉴权，
  是 **401 而非 200**。`{"deleted_journeys": 0}` 只出现在「重新登录后再注销」这条路径上。
  实现正确，是本 issue 原文自相矛盾。）
- 另一个用户的数据在上述任何一步都不受影响（跨用户隔离）。

## 顺带

实现完后更新 `.scratch/rail-journey/spec.md` 的「上线前必办」一节：
把「导出与注销账号仍未做」改成已完成，并把三个新接口补进接口清单。

## Comments

### 实现

- `backend/app/rail/api.py`：新增 `GET /rail/map`、`GET /rail/export`、`DELETE /rail/account`
  三个路由，都只走 `auth.require_rail_user` / `auth.require_user`，不扣 `rail:` 额度。
- `backend/app/auth.py`：新增 `delete_account(openid)`，删身份 + 内部账号 + 全部 session，
  返回被删的 `user_id`（查不到返回 `None`，幂等）。

几处实现取舍：

1. **`/rail/map` 的遍历逻辑照搬 `stats`**：同一个 `stops_cache` 按车次缓存的写法、
   同一个 `from_seq <= seq <= to_seq` 的区段切法、同一个「手填记录回查 `store.get_station`」
   的分支。两个接口对「到过哪些站」必须同口径，否则地图上的点数和统计卡片的站数对不上。
2. **坐标一律过 `geo.wgs84_to_gcj02`**，`legs[].points` 与 `stations[]` 都转，
   `bounds` 由转换后的 `stations` 算出（每个 leg 点都已计入 `stations`，两者覆盖范围等价）。
3. **`delete_account` 按 `user_id` 删 identity，不按 openid 删**。当前只有 `provider='wx'`
   两者等价；但 ADR-0007 为「未来 iOS」留了多渠道的口，届时按 openid 删只会断开微信那一路，
   留下指向已删 `user` 的孤儿身份行。
4. **注销的删除顺序是「先业务数据、后身份」**。反过来 `user_id` 就查不回来了，
   `journey` 表会留下一堆谁也删不掉的孤儿行。
5. **`auth.py` 的返回标注没写 `str | None`**：venv 是 Python 3.9，函数签名里的 `X | Y`
   在 3.9 会在导入期抛 `TypeError`（PEP 604 要 3.10）。改为不标注返回类型。

### 偏离契约之处

- **`/rail/export` 的每条记录比 issue 里的示例多两个字段：`stale` 和 `updated_at`。**
  issue 只点名剔除 `id`/`user_id`/`from_seq`/`to_seq` 四个，我按这条执行，
  没有额外裁剪 `_enrich` 的产物——`stale=true` 恰好向用户解释了「这条为什么没有时刻和里程」，
  裁掉反而让导出文件变得难以自解释。如果要严格对齐示例，说一声我去掉。
- **`/rail/map` 会跳过没有坐标的站**（`lat`/`lon` 为 `NULL`）。这类站画不了点也进不了
  `bounds`。实测 5386 个站坐标齐全，本次验收未触发该分支，
  故「`points` 数量等于区段站数」这条成立；但理论上存在坐标缺失时两者不等的情况。

### 关于 `/rail/map` 契约的疑问（**未擅自改动，按原契约实现**）

1. **`legs` 的顺序未定义**。当前沿用 `journey.list_for` 的 `ride_date DESC`，
   于是 `legs[0]` 是**最近一次**乘车。验收里「北京南在 `legs[0].points[0]`」这条
   我是靠把北京南那条记录的日期设成最新才命中的——不是接口保证。
   小程序地图页如果依赖「第 0 条是某条特定记录」会踩坑，建议明确写成按日期倒序。
2. **`stations[].count` 的语义是「出现次数」而非「去过几次」**。一趟车若两次经停同名站
   （环线/折返），同一条记录会给该站 +2。实测本次数据未出现，但口径值得确认。
3. **没有 `train_number` 之外的 leg 元数据**（如 `stale`、`class`、`distance_km`）。
   地图页若要在点击连线时显示里程，现在得另外调 `/rail/journeys`。按契约先不加。

### 验收实跑输出

环境：`backend/.venv`（Python 3.9.6），`python -m uvicorn app.main:app --port 8765`。
`rail.db` 本地不存在，先跑 `python -m scripts.sync_gtfs` 建库：
`station=5386  train=13891  train_stop=123998  train_number_alias=21832`，
版本 `gtfs-20260913-040340`。

登录态：微信 `code2session` 本地跑不通（`.env` 无 `WX_APPSECRET`，且 code 要真机）。
用临时脚本直接往 `session` 表插行——这正是 `auth.login()` 拿到 openid 之后做的事，
**没有改动任何生产代码的鉴权逻辑**，验收完脚本已删、测试数据已清。

测试数据（用户 A）：G1 seq1..7、K551/K554 seq3..8（用票面别名 `K554` 录入）、
手填 拉萨→日喀则。用户 B 另建 1 条 G2 作跨用户对照。

**① `GET /rail/map` 结构**

```
legs 条数 = 2
  leg: G1 2026-09-14 points = 7 首站 = 北京南 末站 = 上海虹桥
  leg: K551/K554 2026-08-01 points = 6 首站 = 朗乡 末站 = 呼兰
stations 去重数 = 15
含手填站 拉萨 = True count = 1
含手填站 日喀则 = True count = 1
bounds = {"min_lat": 29.220560145162892, "min_lon": 88.91418393275993,
          "max_lat": 46.97440240950721, "max_lon": 128.87875749343976}
```

G1 的 seq1..7 = 7 站、K551/K554 的 seq3..8 = 6 站，`points` 数量与区段站数逐条相等；
手填记录未进 `legs`，其两个站名进了 `stations`；15 = 7 + 6 + 2。

**② 坐标确实转过 GCJ-02**

```
站名 = 北京南  接口 lat/lon = 39.864866353734804 116.37861650604077
库里 WGS84 原值   = 39.8634831 116.3723994
lat 约 39.86 ?    True
与 WGS84 原值不同 ? True
偏移距离 = 552.5 米
```

552.5 米与 `geo.py` 文档里记的「实测北京南站 553 米」吻合。

**③ `GET /rail/export`**

```
export.journey_count = 3  stats.journey_count = 3  一致 = True
exported_at = 2026-09-17T13:41:39
命中禁止字段 = 无
每条记录的字段 = ['arrival', 'created_at', 'day_offset', 'departure', 'distance_km',
                'from_station', 'gtfs_version', 'note', 'ride_date', 'source',
                'stale', 'to_station', 'train_number', 'updated_at']
```

首条记录：`G1 / 2026-09-14 / 北京南→上海虹桥 / 06:30→11:24 / distance_km 1318.0`
——与 spec 里记的京沪高铁官方营业里程 1318km 一致。
手填那条 `distance_km`/`departure`/`arrival` 均为 `null`（不编造时刻）。

**④ 日额度确实不扣**

```
调 /rail/map + /rail/export 前： rail: 额度已用 = 2
调 /rail/map + /rail/export 后： rail: 额度已用 = 2
（对照）再调一次 /rail/trains/G1 → rail: 额度已用 = 3
```

**⑤ `DELETE /rail/account` 真删三处**

```
注销前： identity.user_id = b9e1b21a32744083 | user 行 = 1 | journey 行 = 3 | session 行 = 1
DELETE /rail/account → {"deleted_journeys":3} [HTTP 200]
注销后： identity.user_id = None | user 行 = 0 | journey 行 = 0 | session 行 = 0
旧 token GET /rail/journeys → {"detail":"登录已失效，请重新登录。"} [HTTP 401]
```

**⑥ 重新登录后从零开始**

```
新 user_id = 52dee39be0abfde3   （旧的是 b9e1b21a32744083，确已换新）
GET /rail/stats  → {"journey_count":0,"total_km":0.0,"station_count":0,"city_count":0,
                    "province_count":0,"class_counts":{},"first_ride":null,"latest_ride":null}
GET /rail/map    → {"legs":[],"stations":[],"bounds":null}
GET /rail/export → {"exported_at":"2026-09-17T13:42:13","journey_count":0,"journeys":[]}
```

`user_id` 变了，确认 `user_id_of` 走的是「查不到就新建」而非缓存旧值。

**⑦ 幂等**

```
第 2 次 DELETE /rail/account（旧 token） → [HTTP 401] 登录已失效
重新登录后再 DELETE /rail/account       → {"deleted_journeys":0} [HTTP 200]
auth.delete_account('openid_test_A') 连调 3 次 → None / None / None
auth.delete_account('openid_never_existed')   → None
```

⚠️ 这里和 issue 的措辞有出入，说明一下：issue 写「第二次返回 `{"deleted_journeys": 0}`」，
但注销会一并删掉 session，所以**拿旧 token 的第二次调用根本过不了鉴权，是 401 而非 200**。
`{"deleted_journeys": 0}` 只在「重新登录之后再注销」时出现。
验收条目本身写的是「连续两次不报 500」，401 ≠ 500，这条通过；
删除逻辑本身的幂等性我另外在函数级验了（连调 3 次 + 对不存在的 openid 调用，均不抛异常）。

**⑧ 跨用户隔离**：用户 A 全程建记录 / 导出 / 注销 / 重登之后，用户 B——

```
stats  : {"journey_count":1,"total_km":81.0,"station_count":2,...}
map    : legs= 1 stations= [('上海虹桥', 1), ('苏州北', 1)]
export : journey_count= 1
token B 仍有效 (journeys): HTTP 200
B 的 identity/user 仍在 : 455e2591171251fa | user 行 = 1
B 的 session 行数        : 1
B 的 journey 行数        : 1
```

**⑨ 额外边界（用户 C）：停运车次 + 同一区段重复乘坐**

```
legs = [('G1','2026-05-02',2), ('G1','2026-05-01',2)]   ← G99999 已跳过，不报错
stations = [('北京南', 2), ('沧州西', 2)]                  ← 坐两次的站 count=2
export journey_count = 3  其中 stale 的 = ['G99999']
stats  journey_count = 3  station_count = 2
```

停运车次的记录画不进地图但仍计入 `export`/`stats` 的 `journey_count`，
与 `_enrich` 既有的 `stale` 语义一致：记录的价值不随车次停运消失。
