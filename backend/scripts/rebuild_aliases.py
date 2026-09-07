"""重建所有别名向量（受控并发版）：删除现有别名 → 用最新 ALIAS_SYSTEM 重新生成。
正文完全不动。3 路并发 + 429 退避重试 + 单请求 timeout，兼顾速度与稳定。
用法：python -m scripts.rebuild_aliases
"""
import time
from concurrent.futures import ThreadPoolExecutor

from app import store, ingest_url

WORKERS = 2          # 并发路数（温和，避免限流）
MAX_RETRY = 5


def gen_with_backoff(text):
    """生成一条知识的别名，遇限流(429)指数退避重试。generate_aliases 已带 timeout。"""
    for attempt in range(MAX_RETRY):
        try:
            return ingest_url.generate_aliases(text)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower() or "速率" in str(e):
                wait = 5 * (attempt + 1)
                time.sleep(wait)
                continue
            return []
    return []


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
    alias_lists = [[] for _ in docs]
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(gen_with_backoff, store._with_subject(d)): i for i, d in enumerate(docs)}
        for fut in futs:
            i = futs[fut]
            try:
                alias_lists[i] = fut.result()
            except Exception:
                alias_lists[i] = []
            done += 1
            if done % 20 == 0:
                print(f"  进度 {done}/{total}", flush=True)

    # 组装
    a_ids, a_texts, a_metas = [], [], []
    for d, aliases in zip(docs, alias_lists):
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
    print(f"完成：库总计 {col.count()} 条。", flush=True)


if __name__ == "__main__":
    main()

