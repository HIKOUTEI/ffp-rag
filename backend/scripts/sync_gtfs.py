"""每周同步：GTFS release → `rail.db`（整库重建 + 原子替换）。

用法: python -m scripts.sync_gtfs [--zip <本地zip路径>]

**绝不能在 FastAPI 请求进程里跑**：服务是单 worker（ADR-0002），
整库重建会阻塞问答主链路。由宿主 cron 周调本脚本。

数据源与其风险见 docs/adr/0008-gtfs-timetable-source.md。
"""
import argparse
import csv
import io
import os
import shutil
import sys
import zipfile
from datetime import datetime

import requests

from app import config
from app.rail import store

# 上游仓库。ADR-0008 要求自建 fork 兜底——届时改这个环境变量即可，代码不动。
REPO = os.getenv("GTFS_REPO", "wensimehrp/chinese-railway-gtfs")
ASSET = "output_gtfs.zip"
SNAPSHOT_DIR = os.path.join(config.DATA_DIR, "rail_snapshots")

# GTFS 里线路「全线」的伪车次，不是真实列车，必须过滤（实测 783 条 / 7249 停站）
DUMMY_PREFIX = "DUMMY_"

# 车站的城市/省份归属表。离线由 scripts.gen_station_regions 生成并提交进仓库，
# 生产同步只做查表——不在 600m 的容器里加载边界数据跑几何运算。
REGIONS_CSV = os.path.join(os.path.dirname(os.path.abspath(store.__file__)),
                           "station_regions.csv")


def load_regions():
    """station_id → (city, province)。表缺失时返回空字典，同步照常进行。"""
    if not os.path.exists(REGIONS_CSV):
        print(f"  ! 未找到 {REGIONS_CSV}，城市/省份留空")
        return {}
    with open(REGIONS_CSV, encoding="utf-8") as f:
        return {r["station_id"]: (r["city"], r["province"])
                for r in csv.DictReader(f)}


def _rows(zf, name):
    """流式读 zip 内的 CSV，逐行出 dict。"""
    with zf.open(name) as fp:
        yield from csv.DictReader(io.TextIOWrapper(fp, encoding="utf-8"))


def resolve_latest():
    """取最新 release 的 (tag, 下载地址)。"""
    r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=30)
    r.raise_for_status()
    data = r.json()
    for a in data.get("assets", []):
        if a["name"] == ASSET:
            return data["tag_name"], a["browser_download_url"]
    raise SystemExit(f"release {data.get('tag_name')} 中没有 {ASSET}")


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def archive(zip_path, tag):
    """归档快照（issue 02）。失败不影响同步主流程。"""
    try:
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        dest = os.path.join(SNAPSHOT_DIR, f"{tag}.zip")
        if os.path.exists(dest):
            return dest
        shutil.copyfile(zip_path, dest)
        return dest
    except Exception as e:
        print(f"  ! 快照归档失败（不影响同步）: {e}")
        return None


def build(zip_path, tag, db_path):
    """把 GTFS 灌进一个全新的 db 文件。"""
    conn = store.connect(db_path)
    store.create_schema(conn)

    with zipfile.ZipFile(zip_path) as zf:
        # 1) 车站
        regions = load_regions()
        names = {}
        rows = []
        for r in _rows(zf, "stops.txt"):
            names[r["stop_id"]] = r["stop_name"]
            city, province = regions.get(r["stop_id"], ("", ""))
            rows.append((r["stop_id"], r["stop_name"],
                         float(r["stop_lat"]), float(r["stop_lon"]), city, province))
        conn.executemany(
            "INSERT INTO station(id, name, lat, lon, city, province) "
            "VALUES (?,?,?,?,?,?)", rows)
        tagged = sum(1 for r in rows if r[4])
        print(f"  车站 {len(rows)}（{tagged} 个有城市归属）")

        # 2) 车次种别：真实车次的 route_id 形如 CLASS_*，route_long_name 即种别名
        klass = {r["route_id"]: r["route_long_name"] for r in _rows(zf, "routes.txt")}

        # 3) 车次（过滤伪车次）
        trips = {}
        for r in _rows(zf, "trips.txt"):
            if r["trip_id"].startswith(DUMMY_PREFIX):
                continue
            trips[r["trip_id"]] = (r["trip_short_name"], klass.get(r["route_id"], ""))
        print(f"  车次 {len(trips)}（已过滤伪车次）")

        # 4) 停站。一次流式扫描，顺带聚合出每个车次的始发/终到/站数/全程里程，
        #    不依赖文件内的行序。
        agg = {}
        batch = []
        n_stop = 0
        for r in _rows(zf, "stop_times.txt"):
            t = trips.get(r["trip_id"])
            if t is None:          # 伪车次的停站，跳过
                continue
            number = t[0]
            seq = int(r["stop_sequence"])
            dist = float(r["shape_dist_traveled"]) if r.get("shape_dist_traveled") else None
            batch.append((number, seq, r["stop_id"],
                          store.parse_gtfs_time(r["arrival_time"]),
                          store.parse_gtfs_time(r["departure_time"]), dist))
            a = agg.get(number)
            if a is None:
                a = agg[number] = {"cls": t[1], "n": 0, "km": 0.0,
                                   "lo": (seq, r["stop_id"]), "hi": (seq, r["stop_id"])}
            a["n"] += 1
            if dist is not None and dist > a["km"]:
                a["km"] = dist
            if seq < a["lo"][0]:
                a["lo"] = (seq, r["stop_id"])
            if seq > a["hi"][0]:
                a["hi"] = (seq, r["stop_id"])
            if len(batch) >= 20000:
                conn.executemany("INSERT INTO train_stop VALUES (?,?,?,?,?,?)", batch)
                n_stop += len(batch)
                batch = []
        if batch:
            conn.executemany("INSERT INTO train_stop VALUES (?,?,?,?,?,?)", batch)
            n_stop += len(batch)
        print(f"  停站 {n_stop}")

        # 5) 车次汇总 + 检索别名
        conn.executemany(
            "INSERT INTO train(number, class, origin, terminal, stop_count, total_km) "
            "VALUES (?,?,?,?,?,?)",
            [(num, a["cls"], names.get(a["lo"][1], ""), names.get(a["hi"][1], ""),
              a["n"], a["km"]) for num, a in agg.items()])

        aliases = {(al, num) for num in agg for al in store.number_aliases(num)}
        conn.executemany("INSERT INTO train_number_alias VALUES (?,?)", sorted(aliases))
        print(f"  别名 {len(aliases)}")

    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?,?)",
        [("gtfs_version", tag), ("source_repo", REPO),
         ("synced_at", datetime.now().isoformat(timespec="seconds"))])
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="用本地 zip 而非下载（离线调试用）")
    ap.add_argument("--tag", default="local", help="配合 --zip 指定版本号")
    args = ap.parse_args()

    tmp_db = store.DB_PATH + ".tmp"
    tmp_zip = os.path.join(config.DATA_DIR, "_gtfs_download.zip")

    if args.zip:
        zip_path, tag = args.zip, args.tag
    else:
        tag, url = resolve_latest()
        if tag == store.get_meta("gtfs_version"):
            print(f"已是最新版本 {tag}，无需同步。")
            return
        print(f"下载 {tag} …")
        download(url, tmp_zip)
        zip_path = tmp_zip

    print(f"构建 {tmp_db} …")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    try:
        build(zip_path, tag, tmp_db)
        archive(zip_path, tag)
        # 原子替换：替换前旧库始终可读，替换瞬间完成
        os.replace(tmp_db, store.DB_PATH)
    except Exception:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        raise
    finally:
        if not args.zip and os.path.exists(tmp_zip):
            os.remove(tmp_zip)

    print(f"完成。{store.DB_PATH} ← {tag}")
    print("  " + "  ".join(f"{k}={v}" for k, v in store.counts().items()))


if __name__ == "__main__":
    sys.exit(main())
