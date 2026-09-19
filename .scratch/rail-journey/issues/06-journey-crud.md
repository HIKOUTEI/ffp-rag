# 06 · 乘车记录 CRUD 接口

Status: done

Blocked by: 01, 05

## 任务

乘车记录的增删改查。这是本项目**第一份存在服务端的用户业务数据**。

### 表（`journey.db`）

⚠️ **独立于 `rail.db`**。`rail.db` 每周被整库原子替换（issue 01），
用户数据放进去会被周同步冲掉。参考数据可丢弃可重建，乘车记录不可重建。

```
journey(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  train_number TEXT NOT NULL,   -- 完整车次号，如 K551/K554
  ride_date TEXT NOT NULL,      -- YYYY-MM-DD，用户填的乘车日期
  from_seq INTEGER NOT NULL,    -- 上车站在该车次中的 stop_sequence
  to_seq INTEGER NOT NULL,      -- 下车站
  note TEXT,
  gtfs_version TEXT,            -- 录入时所用运行图版本，指向快照（issue 02）
  source TEXT NOT NULL,         -- 'timetable' 自动填充 | 'manual' 手填历史
  created_at TEXT, updated_at TEXT
)
```

索引：`journey(user_id, ride_date DESC)`。

**为什么存 `seq` 而不是站名**：同一车次可能两次经停同名站（环线、折返），
`seq` 才是唯一定位。渲染时用 `seq` 回查 `train_stop` 拿站名/时刻/里程。

**为什么存 `train_number` 而不是外键**：车次会停运，时刻表会改点。
记录必须在车次从 `rail.db` 消失后仍然可读——`source='manual'` 的历史记录本来就可能查无此车。

### 字段范围（第一版最小集）

只存上表字段。**席别 / 车厢座位 / 票价 / 照片暂不做**（spec 未决问题 3）。
`note` 是自由文本兜底。

### 接口（均需 `require_rail_user`，不扣提问额度）

- `POST /rail/journeys` — 新增。`from_seq < to_seq` 校验；
  `source='timetable'` 时校验车次与 seq 在 `train_stop` 中存在。
- `GET /rail/journeys?limit=&offset=` — 按 `ride_date` 倒序。
  每条**回填**站名、发到时刻、区段里程（`dist[to] - dist[from]`）。
  车次已不在库中时回填 `null` 并标 `stale: true`，不报错。
- `PATCH /rail/journeys/{id}` — 改 `note` / `ride_date`。
- `DELETE /rail/journeys/{id}` — 删单条。
- `DELETE /rail/journeys` — 清空全部（个保法要求，见 spec「上线前必办」）。

**越权**：所有读写都必须带 `user_id` 条件，改别人的记录返回 404（不是 403，
不泄露该 id 是否存在）。

### 手填历史行程

`source='manual'` 时不校验车次存在性，`from_seq`/`to_seq` 允许为空，
另存用户手填的起讫站名。**不编造时刻**——这类记录不显示发到时刻，只显示日期与站名。

> 实现时注意：上表尚未为手填记录留站名字段。落地时补 `manual_from` / `manual_to` 两列，
> 或改为 `from_station` / `to_station` 冗余存名 + `seq` 可空。后者更统一，建议采用。

## 验收

- 新增一条 G1 北京南(seq=1) → 上海虹桥(seq=7)，列表回填里程 1318.0 km、发 06:30 到 11:24。
- 新增一条区段 沧州西(2) → 南京南(5)，里程 = 1023 - 210 = 813.0 km。
- `from_seq >= to_seq` 返回 422。
- 用 A 用户的 token 改 B 用户的记录返回 404。
- 手填记录（`source='manual'`、车次库中不存在）能正常存取，不报错、不显示时刻。
- `DELETE /rail/journeys` 后列表为空。

## Comments

### 2026-09-17 实现完成

`backend/app/rail/journey.py`（`journey.db` 存储层）
+ `backend/app/rail/schemas.py` + `api.py` 里的 5 个路由。

**采纳了本 issue 末尾建议的那版表结构**：`from_station` / `to_station` 冗余存名、
`from_seq` / `to_seq` 可空。手填记录只有站名，而自动填充的记录靠冗余的站名
在车次停运后仍能显示「我坐过哪到哪」——两种来源共用一套字段，比另加两列干净。

验收实跑：

```
G1 北京南(1)→上海虹桥(7)  发06:30 到11:24 (+0天) 1318.0km
G1 沧州西(2)→南京南(5)    发07:20 到10:13 813.0km   （= 1023 − 210 ✓）
K318 → 解析为 K315/K318，喀什→重庆西 发22:43 到05:30 (+3天) 4022.0km
from_seq>=to_seq / seq 不存在 / 车次不存在 / 日期非法 / source 非法 → 全 422
手填 T7788 汉口→襄阳：存取正常，时刻与里程均为 null，不报错
B 改/删 A 的记录 → 404（不是 403）；B 的列表为空
DELETE /rail/journeys → deleted:3，之后列表为空
停运车次（seq 查不到）→ stale:true，站名仍在，不报错
未登录 → 401
DATA_DIR 下 journey.db 与 rail.db 各自独立 ✓
```

### 三个实现决定

- **`day_offset` 是相对上车日的天数**，不是相对始发日。库里存的是自始发起的分钟数，
  但用户关心的是「我上车后第几天到」。喀什→重庆西整程即 +3 天。
- **`PATCH` 只放开 `ride_date` 和 `note`**。改车次或改上下车站等于换了一段经历，
  让用户删了重记比允许原地改更清楚，也省掉一次里程/时刻的重新校验。
- **列表回填带按车次的请求内缓存**。一页 50 条里同一车次常出现多次（通勤线路），
  缓存后 `get_stops` 的调用次数从记录数降到去重车次数。
