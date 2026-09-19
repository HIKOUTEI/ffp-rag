"""重建所有别名向量（受控并发版）：删除现有别名 → 用最新 ALIAS_SYSTEM 重新生成。
正文完全不动。2 路并发 + 429 退避重试 + 单请求 timeout，兼顾速度与稳定。
用法：python -m scripts.rebuild_aliases

只想补「缺别名」的正文用 `python -m scripts.check_aliases --backfill`，便宜得多。
"""
from concurrent.futures import ThreadPoolExecutor

from app import ingest_url, store

WORKERS = 2          # 并发路数（温和，避免限流）


def main():
    col = store.get_collection()

    before = col.count()
    try:
        col.delete(where={"kind": "alias"})
    except Exception as e:
        print("删除别名出错：", e)
    print(f"删除旧别名：{before} → {col.count()}", flush=True)

    docs = store.all_docs()
    total = len(docs)
    print(f"为 {total} 条正文重新生成别名（{WORKERS} 路并发）…", flush=True)

    # 并发生成，保持与 docs 对齐（带主体，避免 AI 抓错主体）
    results = [([], None)] * total
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(ingest_url.generate_aliases_with_retry, store._with_subject(d)): i
                for i, d in enumerate(docs)}
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
    for d, (_, err) in zip(docs, results):
        if err:
            print(f"  ✗ {d['id']} [{d.get('source', '?')}]：{err}")

    # 组装
    a_ids, a_texts, a_metas = [], [], []
    for d, (aliases, _) in zip(docs, results):
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

    if a_ids:
        print(f"生成完成，写入 {len(a_ids)} 条别名…", flush=True)
        B = 50   # 智谱 embedding 单次最多 64 条，取 50 稳妥
        for i in range(0, len(a_ids), B):
            col.add(ids=a_ids[i:i+B], embeddings=store.embed(a_texts[i:i+B]),
                    documents=a_texts[i:i+B], metadatas=a_metas[i:i+B])
    still = len(store.docs_missing_aliases())
    print(f"完成：库总计 {col.count()} 条，仍缺别名的正文 {still} 条。", flush=True)


if __name__ == "__main__":
    main()

