"""坐标系转换：WGS84（GTFS 原始数据）→ GCJ-02（微信小程序 `<map>`）。

不转的后果是整体偏移 300~600 米——实测北京南站 553 米，
车站标记会落到铁轨旁的居民楼上，用户一眼就看得出错位。

**只在接口返回时转，库里始终存 WGS84 原值**（见 issue 03）。
原因是原始数据保真：将来接入非腾讯地图（iOS 走苹果/高德）要的坐标系不同，
而距离计算又必须用 WGS84。存转换后的值等于把一次不可逆的有损变换焊死进库里。
"""
import math

# 国测局偏移算法使用的克拉索夫斯基椭球参数
A = 6378245.0          # 长半轴
EE = 0.00669342162296594323   # 偏心率平方

PI = math.pi
X_PI = PI * 3000.0 / 180.0


def _transform_lat(x, y):
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x, y):
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def out_of_china(lat, lon):
    """粗略的中国境内包围盒判定。

    GCJ-02 只在中国境内定义，境外坐标必须原样返回。全国铁路站点都在境内，
    保留这个分支是为了边境站（满洲里、凭祥）附近的异常输入不被错误偏移。
    """
    if not (72.004 <= lon <= 137.8347):
        return True
    return not (0.8293 <= lat <= 55.8271)


def wgs84_to_gcj02(lat, lon):
    """WGS84 → GCJ-02，返回 `(lat, lon)`。境外坐标与 None 原样返回。"""
    if lat is None or lon is None:
        return lat, lon
    if out_of_china(lat, lon):
        return lat, lon

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)

    rad = lat / 180.0 * PI
    magic = math.sin(rad)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    dlon = (dlon * 180.0) / (A / sqrt_magic * math.cos(rad) * PI)
    return lat + dlat, lon + dlon


def convert_points(points, lat_key="lat", lon_key="lon"):
    """就地转换一组 dict（如 `store.get_stops()` 的返回），返回同一列表。

    接口层的常规用法：查出来是 WGS84，吐出去之前整体过一遍。
    """
    for p in points:
        p[lat_key], p[lon_key] = wgs84_to_gcj02(p.get(lat_key), p.get(lon_key))
    return points


def distance_m(lat1, lon1, lat2, lon2):
    """两点球面距离（米）。**必须传 WGS84**，用来核对偏移量与做距离估算。"""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
