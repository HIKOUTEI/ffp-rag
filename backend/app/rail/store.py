"""`rail.db` —— 共享的铁路参考数据（车站 / 车次 / 车次时刻表）。

只读层。建库与灌数由 `scripts/sync_gtfs.py` 负责，本模块只提供表结构定义与查询。
用户的乘车记录不在这里，见 `app/rail/journey.py`（issue 06）。

时刻一律以「自始发 00:00 起的分钟数」存储，可 >1440。
GTFS 用 `HH:MM:SS` 且 HH 可 ≥24（实测最大 `77:30:00`，即第 4 天），
`datetime.time` 容不下，故不用它。
"""
import os
import sqlite3

from app import config

DB_PATH = os.path.join(config.DATA_DIR, "rail.db")

SCHEMA = """
CREATE TABLE station (
  id       TEXT PRIMARY KEY,   -- GTFS stop_id，形如 STN_北京南
  name     TEXT NOT NULL,
  lat      REAL,               -- WGS84 原值。转 GCJ-02 在接口返回时做，不在这里
  lon      REAL,
  city     TEXT,               -- 坐标反查行政区划得到，同步时可为空（issue 07）
  province TEXT
);

CREATE TABLE train (
  number     TEXT PRIMARY KEY, -- 车次号，如 G1、K551/K554
  class      TEXT,             -- 车次种别，实测 13 类，如「高速动车」「新空调快速」
  origin     TEXT,             -- 始发站名
  terminal   TEXT,             -- 终到站名
  stop_count INTEGER,
  total_km   REAL              -- 全程营业里程
);

CREATE TABLE train_stop (
  train_number  TEXT NOT NULL,
  seq           INTEGER NOT NULL,  -- GTFS stop_sequence
  station_id    TEXT NOT NULL,
  arrival_min   INTEGER,           -- 自始发 00:00 起的分钟数，可 >1440
  departure_min INTEGER,
  dist_km       REAL,              -- 累计营业里程
  PRIMARY KEY (train_number, seq)
);

-- 跨线换号检索用：29% 的车次号含 '/'（如 K551/K554），
-- 而用户车票上只印其中一段。每段与完整号各写一行。
CREATE TABLE train_number_alias (
  alias        TEXT NOT NULL,
  train_number TEXT NOT NULL,
  PRIMARY KEY (alias, train_number)
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX idx_stop_station ON train_stop(station_id);
CREATE INDEX idx_station_name ON station(name);
CREATE INDEX idx_alias        ON train_number_alias(alias);
"""


def connect(path=None):
    """可写连接，供同步脚本建库。日常查询用 `_read()`。"""
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _read():
    """只读连接；库不存在或尚未同步过时返回 None。

    用只读 URI 打开是有意的：`sqlite3.connect()` 对不存在的路径会**建一个空文件**，
    于是首次部署（还没同步过）会留下一个空 `rail.db`，让后续代码误以为库已就绪。
    """
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def ready():
    """参考数据是否已同步就绪。供 /health 与接口层前置检查。"""
    return get_meta("gtfs_version") is not None


def create_schema(conn):
    conn.executescript(SCHEMA)


def parse_gtfs_time(s):
    """`HH:MM:SS` → 自始发 00:00 起的分钟数。HH 可 ≥24。空值返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def format_time(minutes):
    """分钟数 → (`"HH:MM"`, day_offset)。供接口渲染，见 issue 04。

    库里存的是自始发起的总分钟数，直接格式化会得到 `25:30` 这种非法时刻。
    """
    if minutes is None:
        return None, 0
    day, rem = divmod(int(minutes), 1440)
    return f"{rem // 60:02d}:{rem % 60:02d}", day


def number_aliases(number):
    """车次号 → 检索别名集合。`K551/K554` → {K551/K554, K551, K554}。"""
    out = {number}
    if "/" in number:
        out.update(p for p in number.split("/") if p)
    return out


# ---- 查询 ----
#
# 均容忍「库尚未同步」：返回空值而非抛异常。首次部署时 rail.db 还不存在，
# 而同步脚本本身要先读 meta 判断版本——读不了就得当成「没同步过」。

def counts():
    """各表行数，供同步后核对。"""
    c = _read()
    if c is None:
        return {}
    with c:
        try:
            return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("station", "train", "train_stop", "train_number_alias")}
        except sqlite3.Error:
            return {}


def get_meta(key):
    c = _read()
    if c is None:
        return None
    with c:
        try:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        except sqlite3.Error:      # 库存在但没建表（同步半途失败留下的残骸）
            return None
    return row["value"] if row else None


def get_train(number):
    c = _read()
    if c is None:
        return None
    with c:
        row = c.execute("SELECT * FROM train WHERE number=?", (number,)).fetchone()
    return dict(row) if row else None


def _like_prefix(q):
    """把用户输入转成安全的 LIKE 前缀模式。

    车次号里不会有 `%` 和 `_`，但用户输入里可能有——不转义的话一个 `%`
    就是一次全表扫描并返回 20 条无意义结果。
    """
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "%"


def resolve_number(number):
    """把用户输入的车次号解析成库中的完整车次号；解析不出返回 None。

    `K554` → `K551/K554`，`g1` → `G1`。车票上只印跨线换号的其中一段，
    用户照着票填，所以入口一律先过这里。
    """
    if not number:
        return None
    number = number.strip().upper()
    c = _read()
    if c is None:
        return None
    with c:
        row = c.execute("SELECT number FROM train WHERE number=?", (number,)).fetchone()
        if row:
            return row["number"]
        row = c.execute(
            "SELECT train_number FROM train_number_alias WHERE alias=? "
            "ORDER BY LENGTH(train_number), train_number LIMIT 1", (number,)
        ).fetchone()
    return row["train_number"] if row else None


def search_trains(q, limit=20):
    """车次号前缀检索，供录入时的输入联想。空 `q` 返回空列表。"""
    q = (q or "").strip().upper()
    if not q:
        return []
    c = _read()
    if c is None:
        return []
    with c:
        rows = c.execute(
            "SELECT DISTINCT t.number, t.class, t.origin, t.terminal, "
            "       t.stop_count, t.total_km "
            "FROM train_number_alias a JOIN train t ON t.number = a.train_number "
            "WHERE a.alias LIKE ? ESCAPE '\\' "
            # 完全命中的排最前（用户输的就是票面那个号），其余按号长再按字典序，
            # 保证同一输入每次返回顺序一致
            "ORDER BY (a.alias = ?) DESC, LENGTH(t.number), t.number "
            "LIMIT ?", (_like_prefix(q), q, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stops(number):
    """某车次的全程停站，按 seq 升序。带站名、WGS84 坐标与行政区划。"""
    c = _read()
    if c is None:
        return []
    with c:
        rows = c.execute(
            "SELECT ts.seq, ts.station_id, s.name AS station, s.lat, s.lon, "
            "       s.city, s.province, "
            "       ts.arrival_min, ts.departure_min, ts.dist_km "
            "FROM train_stop ts JOIN station s ON s.id = ts.station_id "
            "WHERE ts.train_number=? ORDER BY ts.seq", (number,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_station(name):
    """按站名取车站。站名唯一（`stop_id` 即 `STN_<站名>`），可安全作键。"""
    c = _read()
    if c is None or not name:
        return None
    with c:
        row = c.execute("SELECT * FROM station WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None
