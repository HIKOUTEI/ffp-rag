"""离线生成车站的城市/省份归属表 → `app/rail/station_regions.csv`。

用法: python -m scripts.gen_station_regions [--src <本地边界目录>]

**这是开发期一次性脚本，不在生产跑。** 产物 CSV 提交进仓库，
生产同步（`scripts.sync_gtfs`）只做字典查表。这么切的理由：
部署机容器 `mem_limit` 只有 600m 且与 FastAPI/chromadb 共用，
不值得为一年改动几次的行政区划在生产常驻一份 20MB 边界数据和一个几何库。

新开车站在 CSV 刷新前 city/province 为空——重跑本脚本即可补上。

## 为什么是坐标反查而不是按站名推断

实测：取 717 个「站名以某市名开头」的车站做对照，坐标反查与站名推断有 27 处不一致，
**27 处全部是站名推断错**——朝阳镇在通化、朝阳川在延边、南阳寨在郑州、
北屯在保定、金华镇在贵阳。站名推断不可用。

## 坐标系

边界取自阿里 DataV GeoAtlas。实测把车站坐标按 WGS84 原值与转成 GCJ-02 各跑一遍，
命中结果**完全相同**——两者相差约 550m，相对市级多边形太小，判别不出来。
故直接用库里的 WGS84 原值。代价是距边界 500m 以内的车站可能归错市，属可接受误差。
"""
import argparse
import csv
import json
import os
import sys
import urllib.request

from app.rail import store

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "rail", "station_regions.csv")
BOUND_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{}_full.json"
CACHE = "/tmp/datav_bounds"

# 直辖市在 DataV 里的下级是「西城区」「浦东新区」这类市辖区，不是城市。
# 统计「去过多少城市」时它们应当算作一座城市，故归一到直辖市本身。
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}


def _fetch(adcode, src):
    path = os.path.join(src, f"{adcode}_full.json")
    if not os.path.exists(path):
        urllib.request.urlretrieve(BOUND_URL.format(adcode), path)
    return json.load(open(path, encoding="utf-8"))


def _outer_rings(geom):
    """只取外环。行政区划里的洞（飞地包围）少到可以忽略。"""
    t, c = geom["type"], geom["coordinates"]
    return [c[0]] if t == "Polygon" else [poly[0] for poly in c]


def load_polygons(src):
    """→ [(minx, miny, maxx, maxy, ring, city, province)]，带包围盒供快速排除。"""
    os.makedirs(src, exist_ok=True)
    provinces = _fetch(100000, src)["features"]
    polys = []
    for pf in provinces:
        pac, pname = pf["properties"]["adcode"], pf["properties"]["name"]
        if not isinstance(pac, int):
            continue                      # 100000_JD 是九段线，不是省
        try:
            cities = _fetch(pac, src)["features"]
        except Exception as e:
            print(f"  ! 跳过 {pname}（{pac}）: {e}")
            continue
        for cf in cities:
            if not cf.get("geometry"):
                continue
            city = pname if pname in MUNICIPALITIES else cf["properties"]["name"]
            for ring in _outer_rings(cf["geometry"]):
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                polys.append((min(xs), min(ys), max(xs), max(ys), ring, city, pname))
    return polys


def _in_ring(ring, x, y):
    """射线法。ring 是 [lon, lat] 序列。"""
    n = len(ring)
    j = n - 1
    hit = False
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def locate(polys, lat, lon):
    for minx, miny, maxx, maxy, ring, city, prov in polys:
        if minx <= lon <= maxx and miny <= lat <= maxy and _in_ring(ring, lon, lat):
            return city, prov
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=CACHE, help="边界 GeoJSON 缓存目录")
    args = ap.parse_args()

    if not store.ready():
        raise SystemExit("rail.db 尚未同步，先跑 python -m scripts.sync_gtfs")

    print("加载行政区划边界 …")
    polys = load_polygons(args.src)
    print(f"  外环 {len(polys)}，市 {len({p[5] for p in polys})}，省 {len({p[6] for p in polys})}")

    c = store._read()
    with c:
        rows = c.execute("SELECT id, name, lat, lon FROM station ORDER BY id").fetchall()

    out, miss = [], []
    for r in rows:
        city, prov = locate(polys, r["lat"], r["lon"])
        out.append((r["id"], city, prov))
        if not city:
            miss.append(r["name"])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["station_id", "city", "province"])
        w.writerows(out)

    n = len(out)
    print(f"写入 {OUT}")
    print(f"  {n} 站，归属成功 {n - len(miss)}（{(n - len(miss)) / n:.1%}），落空 {len(miss)}")
    if miss:
        print("  落空示例:", "、".join(miss[:15]))


if __name__ == "__main__":
    sys.exit(main())
