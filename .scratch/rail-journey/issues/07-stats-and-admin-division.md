# 07 · 统计聚合接口（含车站城市/省份归属）

Status: done

Blocked by: 01, 06

## 任务

`GET /rail/stats` — 用户的铁路版图汇总，供「行程」tab 首屏。

```json
{
  "journey_count": 42, "total_km": 28461.0,
  "station_count": 87, "city_count": 53, "province_count": 19,
  "class_counts": {"高速动车": 30, "动车组": 8, "新空调快速": 4},
  "first_ride": "2019-03-12", "latest_ride": "2026-09-14"
}
```

- `total_km` = 各条记录区段里程之和（`dist[to] - dist[from]`）。手填记录无里程，跳过。
- `station_count` 按**去重的途经车站**计——用户坐 seq 3→9，途中 7 个站都算"到过"。
  （这是打卡语义：车经过了就算走过那条线。若认为只有上下车站才算，需在此明确改掉。）
- `class_counts` 取自 `train.class`，即 GTFS `route_long_name`（实测 13 类，
  最多的是「高速动车」5026 个车次，其次「动车组」「城际高速」）。

## ⚠️ 子问题：城市与省份从哪来

**GTFS 完全没有行政区划信息**，`stops.txt` 只有 `stop_id,stop_name,stop_lat,stop_lon`。
而 city/province 是统计里最有打卡感的两个数字。两条路：

**A. 按站名推断** —— 零依赖，但**不可靠**。
`南京南`→南京 ✅，但 `汉口`→武汉 ✗、`羊城`类老站名 ✗、`一二九公里` ✗（真实站名，实测存在）。
5386 个站里有大量这种站，错误率无法接受。

**B. 坐标反查行政区划** —— 引入一份省市边界 GeoJSON，点在多边形内判断。**推荐**。
- 只在 **GTFS 同步时**跑一次，结果写进 `station.city` / `station.province` 两列，
  查询时零成本。
- 全国市级边界 GeoJSON 约 10~20MB，只在同步脚本里加载，不进 FastAPI 进程内存。
- 5386 个点 × 市级多边形，用 `shapely` + STRtree 索引，几秒内跑完。
- 边界数据源需另行确认许可证——这是**本 issue 唯一的外部依赖新增**，
  若嫌重，退化方案是只做省级（数据更小、精度要求更低）。

实现前先确认选 B 并定下边界数据源；`station` 表的这两列在 issue 01 里已预留、同步时留空。

## 验收

- 单条 G1 北京南→上海虹桥记录：`total_km=1318.0`，`station_count=7`，
  `province_count=5`（北京/河北/山东/江苏/上海）。
- 手填记录计入 `journey_count` 但不计入 `total_km`。
- 无任何记录时返回全 0，不报错。
- `station.city` / `station.province` 在同步后非空率 > 95%（剩余是无法归属的工务站点）。

## Comments

### 2026-09-17 实现完成

`GET /rail/stats` 在 `app/rail/api.py`。行政区划走**选项 B（坐标反查）的离线变体**，
见下。

验收实跑：

```
无记录            → 全 0，不报错
单条 G1 北京南→上海虹桥
  total_km=1318.0  station_count=7  city_count=7  province_count=5 ✓
  途经省 北京市/河北省/山东省/山东省/江苏省/江苏省/上海市 → 去重正好 5 个 ✓
+跨日 K315/K318 +手填
  journey_count=3  total_km=5340.0（= 1318+4022，手填不计入）
  station_count=39  city_count=20  province_count=11
station.city / province 非空率 99.7%（5372/5386），验收线是 >95% ✓
```

### 坐标反查 vs 站名推断：有实测结论了

取 717 个「站名以某市名开头」的车站做对照，两法有 27 处不一致，
**27 处全部是站名推断错**，坐标反查一处没错：

```
朝阳镇 → 站名暗示 朝阳市，实际在 通化市
朝阳川 → 站名暗示 朝阳市，实际在 延边朝鲜族自治州
南阳寨 → 站名暗示 南阳市，实际在 郑州市
北屯   → 站名暗示 北屯市，实际在 保定市
金华镇 → 站名暗示 金华市，实际在 贵阳市
```

本 issue 原文说站名推断"错误率无法接受"，现在有数了。

### 实现上偏离原方案的地方（经确认）

原方案是在**生产同步时**加载边界 GeoJSON 跑点在多边形。实现时发现代价比写 issue 时高：
部署机容器 `mem_limit` 只有 600m，且与 FastAPI + chromadb 共用——为一年改几次的
行政区划常驻 20MB 边界数据加一个几何库不划算。

改成**离线预生成**：

- `scripts/gen_station_regions.py` —— 开发期一次性脚本，产出
  `app/rail/station_regions.csv`（5386 行，200KB），提交进仓库。
- `scripts/sync_gtfs.py` 同步时只做字典查表，**零新增依赖、零额外内存**。
- CSV 放 `app/rail/` 而不是 `DATA_DIR`：后者在 compose 里是挂载卷（`/opt/ffp-rag/data`），
  放进去会被卷遮住；`app/` 由 Dockerfile `COPY app ./app` 随镜像走。
- 点在多边形用纯 Python 射线法 + 包围盒预筛，**连 shapely 都没引**，
  生成脚本本身也零依赖，谁都能重跑。

代价：**新开的车站在 CSV 刷新前 city/province 为空**，重跑生成脚本即可补。
`load_regions()` 在 CSV 缺失时返回空字典，同步照常完成。

### 两点需要知道的

**边界数据源是阿里 DataV GeoAtlas**（`geo.datav.aliyun.com/areas_v3`）。
仓库里**只提交派生出来的 station_id→城市/省份映射，不提交边界几何**，
分发面比 ADR-0008 那份 GTFS 小得多。台湾省（710000）接口 404，GTFS 也不覆盖，跳过。

**坐标系不影响结果。** 把车站坐标按 WGS84 原值与转成 GCJ-02 各跑一遍，
命中结果完全相同——两者差约 550m，相对市级多边形太小判别不出。故直接用 WGS84 原值。
残留误差：距市界 500m 以内的车站可能归错市。

### 落空的 14 个站

`万象、琅勃拉邦、孟赛、磨丁、磨憨（境）、纳堆、纳磨、蓬洪、孟阿、嘎西、岔江、万荣`
——**中老铁路的老挝段**，本就在中国境外，算法判对了。
另有 `石家村所`（工务站点）、`赣榆`（贴近市界）两个是真落空。

### 一处仍需留意

`station_count` 现在按**去重途经车站**计（坐 3→9，途中 7 站都算到过），
`city_count` / `province_count` 同理。本 issue 原文已标注这是打卡语义、
若认为"只有上下车站才算"需在此改掉——**保持了原语义，未改**。
