"""别名健康度检查 + 增量补齐。

用法:
    python -m scripts.check_aliases              # 只读报告，不调 AI、不花钱
    python -m scripts.check_aliases --backfill   # 只给缺别名的正文补生成（花额度）

与 `rebuild_aliases.py` 的分工：
  - `rebuild_aliases`  全删重建，适合改了 ALIAS_SYSTEM 之后整体重做，贵。
  - 本脚本 `--backfill` 只补「一条别名都没有」的正文，适合入库时生成失败后的补偿。

覆盖率由库里 alias 的 parent_id 反查得出（见 `store.docs_missing_aliases`），
不依赖任何额外账本，所以不会出现「账本说补过了但实际没有」。
"""
import argparse
from concurrent.futures import ThreadPoolExecutor

from app import ingest_url, store

WORKERS = 2          # 并发路数（温和，避免限流）


def report():
    """打印覆盖率，返回缺别名的正文列表。只读，不花钱。"""
    docs = store.all_docs()
    missing = store.docs_missing_aliases()
    total = len(docs)
    covered = total - len(missing)
    rate = covered / total if total else 1.0

    print(f"正文条数     : {total}")
    print(f"有别名的正文 : {covered}  ({rate:.1%})")
    print(f"缺别名的正文 : {len(missing)}")

    if missing:
        print("\n缺别名的正文（最多列 20 条）:")
        for d in missing[:20]:
            print(f"  {d['id']}  [{d.get('source', '?')}]  {d['text'][:40]}…")
        if len(missing) > 20:
            print(f"  …另有 {len(missing) - 20} 条")
        print("\n补齐: python -m scripts.check_aliases --backfill")
    return missing


def backfill(missing):
    """只给缺别名的正文生成并写入别名。"""
    if not missing:
        print("\n无需补齐。")
        return
    total = len(missing)
    print(f"\n为 {total} 条正文补生成别名（{WORKERS} 路并发）…", flush=True)

    results = [([], None)] * total
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(ingest_url.generate_aliases_with_retry, store._with_subject(d)): i
                for i, d in enumerate(missing)}
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = ([], e)
            done += 1
            if done % 20 == 0:
                print(f"  进度 {done}/{total}", flush=True)

    # 失败的逐条报出来，不再静默
    failed = [(missing[i], err) for i, (_, err) in enumerate(results) if err]
    for d, err in failed:
        print(f"  ✗ {d['id']} [{d.get('source', '?')}]：{err}")

    a_ids, a_texts, a_metas = [], [], []
    for d, (aliases, _) in zip(missing, results):
        for j, q in enumerate(aliases):
            a_ids.append(f"{d['id']}-alias-{j}")
            a_texts.append(q)
            a_metas.append({
                "domain": d.get("domain", "other"),
                "subject": d.get("subject", ""),
                "subtopic": d.get("subtopic", ""),
                "source": d.get("source", "?"),
                "url": d.get("url", ""),
                "date": d.get("date", ""),
                "kind": "alias",
                "parent_id": d["id"],
                "parent_text": d["text"],
            })

    if not a_ids:
        print("没有产出任何别名，未写入。")
        return

    col = store.get_collection()
    print(f"写入 {len(a_ids)} 条别名…", flush=True)
    B = 50   # 智谱 embedding 单次最多 64 条，取 50 稳妥
    for i in range(0, len(a_ids), B):
        col.add(ids=a_ids[i:i + B], embeddings=store.embed(a_texts[i:i + B]),
                documents=a_texts[i:i + B], metadatas=a_metas[i:i + B])

    still = len(store.docs_missing_aliases())
    print(f"完成：{total - still} 条补上，仍缺 {still} 条。")


def main():
    ap = argparse.ArgumentParser(description="别名健康度检查与增量补齐")
    ap.add_argument("--backfill", action="store_true",
                    help="给缺别名的正文补生成（会调用 AI，消耗额度）")
    args = ap.parse_args()

    missing = report()
    if args.backfill:
        backfill(missing)


if __name__ == "__main__":
    main()
