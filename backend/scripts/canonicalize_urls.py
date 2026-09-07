"""一次性迁移：把 Chroma 中所有片段的 url metadata 就地规范化重写。
幂等——重复运行第二次变更数应为 0。正文与别名都处理（别名的 url 与其正文保持一致）。
用法：python -m scripts.canonicalize_urls
"""
from app import store
from app.urlutil import canonical_url


def main():
    col = store.get_collection()
    res = col.get(include=["metadatas"])
    ids = res.get("ids", [])
    metas = res.get("metadatas", []) or []
    total = len(ids)
    print(f"库中片段共 {total} 条，开始规范化 url…", flush=True)

    upd_ids, upd_metas = [], []
    for _id, meta in zip(ids, metas):
        meta = meta or {}
        old = meta.get("url", "")
        if not old:
            continue
        new = canonical_url(old)
        if new != old:
            m = dict(meta)
            m["url"] = new
            upd_ids.append(_id)
            upd_metas.append(m)

    if not upd_ids:
        print("无需变更（所有 url 已是规范化形式）。", flush=True)
        return

    print(f"需变更 {len(upd_ids)} 条，写回…", flush=True)
    B = 100
    for i in range(0, len(upd_ids), B):
        col.update(ids=upd_ids[i:i+B], metadatas=upd_metas[i:i+B])
    print(f"完成：变更 {len(upd_ids)}/{total} 条。", flush=True)


if __name__ == "__main__":
    main()
