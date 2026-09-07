"""Chroma 持久化向量库封装。我们自己用 provider 的 embedding，故禁用 Chroma 自带 embedding。"""
import glob
import os
import threading

import chromadb

from app import config
from app.rag import embed
from app.urlutil import canonical_url


def get_client():
    return chromadb.PersistentClient(path=config.CHROMA_DIR)


def get_collection(create=False):
    client = get_client()
    if create:
        # embedding_function=None: 我们自己传向量
        return client.get_or_create_collection(
            name=config.COLLECTION, embedding_function=None
        )
    return client.get_collection(name=config.COLLECTION, embedding_function=None)


def all_docs():
    """取出库中所有正文片段（排除别名），供体检使用。
    返回 list[dict(id, text, domain, subtopic, source, url, date)]。"""
    col = get_collection()
    try:
        res = col.get(where={"kind": "doc"}, include=["documents", "metadatas"])
    except Exception:
        # 兼容旧数据（无 kind 字段）：取全部再过滤掉别名
        res = col.get(include=["documents", "metadatas"])
    out = []
    for _id, doc, meta in zip(res.get("ids", []), res.get("documents", []), res.get("metadatas", [])):
        if meta.get("kind") == "alias":
            continue
        out.append({
            "id": _id,
            "text": doc,
            "domain": meta.get("domain", "other"),
            "subject": meta.get("subject", ""),
            "subtopic": meta.get("subtopic", ""),
            "source": meta.get("source", "?"),
            "url": meta.get("url", ""),
            "date": meta.get("date", ""),
        })
    return out


def parse_corpus_file(path):
    """解析单个 .md：frontmatter 'domain:' / 'source:' + '---' 分隔正文。"""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    domain, source, body = "unknown", os.path.basename(path), raw
    if "---" in raw:
        head, body = raw.split("---", 1)
        for line in head.splitlines():
            if line.startswith("domain:"):
                domain = line.split(":", 1)[1].strip()
            elif line.startswith("source:"):
                source = line.split(":", 1)[1].strip()
    return {"domain": domain, "source": source, "text": body.strip()}


def load_corpus():
    return [
        parse_corpus_file(p)
        for p in sorted(glob.glob(os.path.join(config.CORPUS_DIR, "*.md")))
    ]


def ingest():
    """读语料 → embed → 写入 Chroma（重建集合）。返回写入条数。"""
    client = get_client()
    # 全量重建，避免重复
    try:
        client.delete_collection(config.COLLECTION)
    except Exception:
        pass
    col = client.get_or_create_collection(name=config.COLLECTION, embedding_function=None)

    chunks = load_corpus()
    if not chunks:
        return 0
    embeds = embed([c["text"] for c in chunks])
    col.add(
        ids=[f"chunk-{i}" for i in range(len(chunks))],
        embeddings=embeds,
        documents=[c["text"] for c in chunks],
        metadatas=[{"domain": c["domain"], "source": c["source"], "url": "", "date": "",
                    "subtopic": "", "kind": "doc"} for c in chunks],
    )
    return len(chunks)


def add_fragments(fragments, with_aliases=True, async_aliases=True):
    """向已有集合追加片段（不清空）。每条知识写入正文向量（同步，立即可检索）；
    别名问法默认后台异步生成（不阻塞入库）。
    返回 (added, total)，added 为写入的知识条数（不含别名）。"""
    fragments = [f for f in fragments if (f.get("text") or "").strip()]
    client = get_client()
    col = client.get_or_create_collection(name=config.COLLECTION, embedding_function=None)
    if not fragments:
        return 0, col.count()
    base = col.count()

    # 1) 写入正文向量
    doc_texts = [f["text"] for f in fragments]
    doc_embeds = embed(doc_texts)
    doc_ids, doc_metas = [], []
    for i, f in enumerate(fragments):
        doc_ids.append(f"frag-{base}-{i}")
        doc_metas.append({
            "domain": f.get("domain", "other"),
            "subject": f.get("subject", ""),
            "subtopic": f.get("subtopic", ""),
            "source": f.get("source", "?"),
            "url": canonical_url(f.get("url", "")),
            "date": f.get("date", ""),
            "kind": "doc",
        })
    col.add(ids=doc_ids, embeddings=doc_embeds, documents=doc_texts, metadatas=doc_metas)

    # 2) 别名问法：默认后台异步生成（不阻塞入库，正文已可检索）
    if with_aliases:
        payload = [(doc_ids[i], f) for i, f in enumerate(fragments)]
        if async_aliases:
            threading.Thread(target=_build_aliases, args=(payload,), daemon=True).start()
        else:
            _build_aliases(payload)

    return len(fragments), col.count()


def find_ingested_url(url):
    """判断某 URL 是否已录入（库中存在其规范化 URL 的正文片段）。
    命中返回 {url(规范化), source, date, count}；未命中返回 None。"""
    canon = canonical_url(url)
    if not canon:
        return None
    col = get_collection()
    try:
        res = col.get(where={"$and": [{"url": canon}, {"kind": "doc"}]},
                      include=["metadatas"])
    except Exception:
        return None
    ids = res.get("ids", [])
    if not ids:
        return None
    metas = res.get("metadatas", []) or [{}]
    m = metas[0] or {}
    return {
        "url": canon,
        "source": m.get("source", "?"),
        "date": m.get("date", ""),
        "count": len(ids),
    }

    """把主体拼到正文前，供别名生成时明确主体（避免 AI 抓错主体）。
    f 可为 fragment dict 或含 meta 的 dict。主体缺失则原样返回 text。"""
    text = f.get("text", "")
    subj = (f.get("subject") or "").strip()
    if subj and subj not in text[:40]:
        return f"【主体：{subj}】\n{text}"
    return text


def _build_aliases(payload):
    """为每条知识生成别名问法并写入。payload: list[(doc_id, fragment_dict)]。"""
    from app import ingest_url  # 局部导入避免循环依赖
    try:
        # 别名生成时带上主体，避免 AI 抓错主体（用顺带提及的品牌造问法）
        texts = [_with_subject(f) for _id, f in payload]
        alias_lists = ingest_url.generate_aliases_batch(texts)
        a_ids, a_texts, a_metas = [], [], []
        for (doc_id, f), aliases in zip(payload, alias_lists):
            for j, q in enumerate(aliases):
                a_ids.append(f"{doc_id}-alias-{j}")
                a_texts.append(q)
                a_metas.append({
                    "domain": f.get("domain", "other"),
                    "subject": f.get("subject", ""),
                    "subtopic": f.get("subtopic", ""),
                    "source": f.get("source", "?"),
                    "url": f.get("url", ""),
                    "date": f.get("date", ""),
                    "kind": "alias",
                    "parent_id": doc_id,
                    "parent_text": f["text"],
                })
        if a_ids:
            col = get_client().get_or_create_collection(name=config.COLLECTION, embedding_function=None)
            col.add(ids=a_ids, embeddings=embed(a_texts), documents=a_texts, metadatas=a_metas)
    except Exception:
        pass  # 别名生成失败不影响已入库的正文


def search(query, top_k=None):
    """检索 -> list[dict(domain, source, text, score, url, date)]。
    命中别名问法时回查其指向的正文；按正文去重，保留最高分。"""
    top_k = top_k or config.TOP_K
    col = get_collection()
    qv = embed([query])[0]
    # 多取一些（别名会挤占名额，回查去重后收敛）
    res = col.query(query_embeddings=[qv], n_results=top_k * 3)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    best = {}  # 正文文本 -> 记录（保留最高分）
    for doc, meta, dist in zip(docs, metas, dists):
        score = round(1 - dist, 4)
        if meta.get("kind") == "alias":
            text = meta.get("parent_text", doc)  # 回查正文
        else:
            text = doc
        prev = best.get(text)
        if prev is None or score > prev["score"]:
            best[text] = {
                "domain": meta.get("domain", "?"),
                "source": meta.get("source", "?"),
                "text": text,
                "score": score,
                "url": meta.get("url", ""),
                "date": meta.get("date", ""),
            }
    out = sorted(best.values(), key=lambda x: -x["score"])
    return out[:top_k]


def search_smart(query, top_k=None, expand_threshold=0.35):
    """智能检索：先正常检索；若最高命中分低于阈值（快答不上来），
    用 AI 把问题扩展成多个问法再检索，合并去重。返回 (results, expanded)。
    expanded 为触发扩展时用到的问法列表（供透明展示），未触发则为空。"""
    from app import rag
    top_k = top_k or config.TOP_K
    results = search(query, top_k)
    best = results[0]["score"] if results else 0.0
    if best >= expand_threshold:
        return results, []

    # 命中低 → 扩展问题再检索
    expanded = rag.expand_query(query)
    if not expanded:
        return results, []

    merged = {r["text"]: r for r in results}
    for q in expanded:
        for r in search(q, top_k):
            prev = merged.get(r["text"])
            if prev is None or r["score"] > prev["score"]:
                merged[r["text"]] = r
    out = sorted(merged.values(), key=lambda x: -x["score"])[:top_k]
    return out, expanded


def find_duplicates(texts, threshold=0.90):
    """给一批片段文本，各自在库里找最相似的已有【正文】片段（忽略别名）。
    返回 list[dict|None]：相似度≥threshold 时给 {score, source, text, date, url}，否则 None。"""
    col = get_collection()
    if col.count() == 0 or not texts:
        return [None] * len(texts)
    vecs = embed(texts)
    out = []
    for v in vecs:
        # 只在正文里找重复，排除别名
        res = col.query(query_embeddings=[v], n_results=3,
                        where={"kind": "doc"})
        docs = res["documents"][0]
        if not docs:
            out.append(None)
            continue
        dist = res["distances"][0][0]
        score = round(1 - dist, 4)
        if score >= threshold:
            meta = res["metadatas"][0][0]
            out.append({
                "score": score,
                "source": meta.get("source", "?"),
                "text": docs[0],
                "date": meta.get("date", ""),
                "url": meta.get("url", ""),
            })
        else:
            out.append(None)
    return out


def _delete_aliases_of(col, doc_id):
    """删除某条正文对应的所有别名向量。"""
    try:
        col.delete(where={"parent_id": doc_id})
    except Exception:
        pass


def get_doc(doc_id):
    """按 id 取一条正文片段（含 text 和 metadata）。不存在返回 None。"""
    col = get_collection()
    res = col.get(ids=[doc_id], include=["documents", "metadatas"])
    if not res.get("ids"):
        return None
    return {"id": doc_id, "text": res["documents"][0], "meta": res["metadatas"][0]}


def update_doc(doc_id, new_text):
    """修改一条正文：更新向量+文本，并重建它的别名。返回 (ok, old)。
    调用方负责记历史/日志。"""
    from app import ingest_url
    col = get_collection()
    cur = get_doc(doc_id)
    if not cur or cur["meta"].get("kind") == "alias":
        return False, None
    old = {"text": cur["text"], "meta": dict(cur["meta"])}

    # 1) 更新正文向量与文本
    vec = embed([new_text])[0]
    col.update(ids=[doc_id], embeddings=[vec], documents=[new_text])

    # 2) 重建别名（旧别名删掉，按新文本重生成）
    _delete_aliases_of(col, doc_id)
    meta = cur["meta"]
    aliases = ingest_url.generate_aliases(
        _with_subject({"text": new_text, "subject": meta.get("subject", "")}))
    if aliases:
        a_ids, a_metas = [], []
        for j, q in enumerate(aliases):
            a_ids.append(f"{doc_id}-alias-{j}")
            a_metas.append({
                "domain": meta.get("domain", "other"),
                "subject": meta.get("subject", ""),
                "subtopic": meta.get("subtopic", ""),
                "source": meta.get("source", "?"),
                "url": meta.get("url", ""),
                "date": meta.get("date", ""),
                "kind": "alias",
                "parent_id": doc_id,
                "parent_text": new_text,
            })
        col.add(ids=a_ids, embeddings=embed(aliases), documents=aliases, metadatas=a_metas)
    return True, old


def delete_doc(doc_id):
    """删除一条正文及其所有别名。返回 (ok, old)。"""
    col = get_collection()
    cur = get_doc(doc_id)
    if not cur or cur["meta"].get("kind") == "alias":
        return False, None
    old = {"text": cur["text"], "meta": dict(cur["meta"])}
    _delete_aliases_of(col, doc_id)
    col.delete(ids=[doc_id])
    return True, old
