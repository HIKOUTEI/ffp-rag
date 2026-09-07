"""URL 规范化：把同一篇文章的各种链接变体折叠成唯一形式，用于判重。
详见 docs/adr/0001-url-canonicalization.md。"""
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# 通用追踪参数黑名单：这些参数不影响文章身份，一律剔除。
_TRACKING_PARAMS = {
    "chksm", "scene", "sn", "srcid", "from", "isappinstalled",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "share_token", "clicktime", "enterid", "ascene", "subscene",
    "sessionid", "key", "uin", "devicetype", "version", "nettype", "lang",
    "exportkey", "pass_ticket", "wx_header", "fontgear",
}

# 公众号文章身份参数白名单：只保留这些，其余全丢。
_WECHAT_KEEP = {"__biz", "mid", "idx", "sn"}
_WECHAT_HOST = "mp.weixin.qq.com"


def canonical_url(url: str) -> str:
    """把 URL 归一化为判重用的规范形式。

    - scheme + host 转小写
    - 去掉 `#` 片段
    - 剔除通用追踪参数；公众号 host 则只保留 __biz/mid/idx/sn
    无法解析（空串、非 http 等）时原样返回 strip 后的输入。
    """
    if not url:
        return ""
    url = url.strip()
    try:
        p = urlparse(url)
    except ValueError:
        return url
    if not p.scheme or not p.netloc:
        return url  # 相对路径等，不动

    scheme = p.scheme.lower()
    netloc = p.netloc.lower()

    params = parse_qsl(p.query, keep_blank_values=True)
    if netloc == _WECHAT_HOST:
        kept = [(k, v) for k, v in params if k in _WECHAT_KEEP]
    else:
        kept = [(k, v) for k, v in params if k.lower() not in _TRACKING_PARAMS]
    # 稳定排序，确保参数顺序不同的同一链接归一化结果一致
    kept.sort()
    query = urlencode(kept)

    # 去 fragment（第 6 位置空）
    return urlunparse((scheme, netloc, p.path, p.params, query, ""))
