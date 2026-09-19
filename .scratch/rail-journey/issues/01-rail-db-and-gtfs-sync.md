# 01 · rail.db 表结构与 GTFS 同步脚本

Status: done

## 任务

新建 `app/rail/store.py`（存储层）与 `scripts/sync_gtfs.py`（同步脚本），
把 GTFS 落成可查询的 `rail.db`。

### 表结构（`rail.db`，放 `config.DATA_DIR`）

⚠️ **`rail.db` 只放共享参考数据**。用户的乘车记录另建 `journey.db`（见 issue 06）。
理由：本库每周被**整库原子替换**，用户数据不能进这个爆炸半径。

```
station(
  id TEXT PRIMARY KEY,      -- GTFS stop_id，形如 STN_北京南
  name TEXT NOT NULL,       -- 北京南
  lat REAL, lon REAL,       -- WGS84，直接来自 GTFS
  city TEXT, province TEXT  -- 反查得到，见 issue 07；同步时先留空
)

train(
  number TEXT PRIMARY KEY,  -- 车次号，GTFS trip_short_name，如 G1、K551/K554
  class TEXT,               -- 车次种别，由 route_id 关联 routes.route_long_name 得到
  origin TEXT,              -- 始发站名
  terminal TEXT,            -- 终到站名
  stop_count INTEGER,
  total_km REAL             -- 全程营业里程 = 末站 shape_dist_traveled
)

train_stop(
  train_number TEXT NOT NULL,
  seq INTEGER NOT NULL,     -- GTFS stop_sequence
  station_id TEXT NOT NULL,
  arrival_min INTEGER,      -- 自始发 00:00 起的分钟数，可 >1440（跨日）
  departure_min INTEGER,
  dist_km REAL,             -- 累计营业里程
  PRIMARY KEY (train_number, seq)
)

train_number_alias(          -- 跨线换号检索用，见下
  alias TEXT NOT NULL,       -- K551
  train_number TEXT NOT NULL,-- K551/K554
  PRIMARY KEY (alias, train_number)
)

meta(key TEXT PRIMARY KEY, value TEXT)   -- 记 gtfs_version / synced_at / counts
```

索引：`train_stop(station_id)`、`station(name)`、`train_number_alias(alias)`。

### 同步脚本要点

1. 下载最新 release 的 `output_gtfs.zip`（GitHub API 取 `releases/latest`）。
2. **过滤 783 个 `DUMMY_LINE_*` 伪车次**（`trip_id` 前缀 `DUMMY_`，`route_id` 前缀 `LINE_`），
   只保留 `route_id` 为 `CLASS_*` 的 **13891** 条真实车次。
   伪车次另带 7249 条停站，一并排除，真实停站为 **123998** 条。
3. **时刻解析**：GTFS 用 `HH:MM:SS` 且 `HH` 可 ≥24（实测最大 `77:30:00`）。
   解析成**自始发 00:00 起的总分钟数**，不要用 `datetime.time`——它容不下 24 以上。
4. **跨线换号别名**：29%（3969/13891）的车次号含 `/`，如 `K551/K554`。
   用户车票上只印其中一段。按 `/` 切开，每段各写一行 `train_number_alias`；
   完整车次号本身也写一行。⚠️ 注意 `09/S8512` 这类前段不是完整车次号的情况，
   照样入别名表，检索时一并命中即可。
5. **原子替换**：写到 `rail.db.tmp`，`VACUUM` 后 `os.replace()` 成 `rail.db`。
   **绝不能在 FastAPI 请求进程里跑**——服务是单 worker（ADR-0002），会阻塞问答。
   脚本走 `python -m scripts.sync_gtfs`，由宿主 cron 周调。
6. 同步成功后把 GTFS 版本号（release tag）写进 `meta`。

## 验收

- `python -m scripts.sync_gtfs` 跑完，`rail.db` 中 station=5386、train=13891、train_stop=123998。
- `SELECT * FROM train WHERE number='G1'` → 北京南 / 上海虹桥 / 7 站 / 1318.0 km。
- `G1` 的 `train_stop` 末站 `dist_km` = 1318，首站 = 0。
- 别名表中 `K551` 和 `K554` 都能指向 `K551/K554`。
- 存在 `arrival_min > 1440` 的记录（跨日车次），最大值接近 `77*60+30 = 4650`。
- 同步过程中旧 `rail.db` 始终可读，替换瞬间完成。
- 重复跑两次结果一致（幂等）。

## Comments

### 2026-09-17 实现完成

`backend/app/rail/store.py` + `backend/scripts/sync_gtfs.py`。实跑验收全过：

```
车站 5386  车次 13891（已过滤伪车次）  停站 123998  别名 21832
G1 → 高速动车 / 北京南 / 上海虹桥 / 7 站 / 1318.0 km，首站 dist=0 末站 dist=1318
K551、K554、K551/K554 三个别名均指向 K551/K554
MAX(arrival_min) = 4650 = 77×60+30，与预测一致
重复跑两次计数完全相同（幂等）
```

两处偏离 spec 的实现决定：

- **没做 `VACUUM`**。整库是一次性顺序 INSERT 建成的，没有删除产生的空洞，
  VACUUM 只是多花一遍全库拷贝时间。
- **车次汇总（始发/终到/站数/全程里程）在扫 `stop_times` 时单趟聚合得出**，
  而不是建完表再回查。`stop_times.txt` 12 万行，回查是 13891 次额外查询。
  聚合按 `seq` 取极值，不依赖文件内的行序。

另修了一个首次部署会崩的 bug：同步脚本开头要读 `meta` 判断版本，
而首次部署时 `rail.db` 还不存在。更糟的是 `sqlite3.connect()` 对不存在的路径
**会建一个空文件**，于是留下一个空 `rail.db` 让后续代码误以为库已就绪。
改用只读 URI（`file:...?mode=ro`, `uri=True`）打开，并给所有查询函数加了空库保护。
已验证首次运行返回 `None`/`{}`/`[]` 且不留下空文件。
