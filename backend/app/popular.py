"""提问记录 + 热门榜。

- SQLite 一张表 template_hits(template_id, question_text, count)。
- record(question): 用 embedding 把提问归到最近的问题模板，
  cosine 相似度 >= THRESHOLD 才计数；否则不计入。
- top(n): 按 count 倒序取 n 条；全 0（冷启动）时按模板预设顺序返回。

模板向量在首次使用时预计算并缓存在内存。所有操作对异常容错，
失败不影响问答主链路。
"""
import math
import os
import sqlite3
import threading

from app import config, rag
from app.templates import TEMPLATES

DB_PATH = os.path.join(config.BACKEND_DIR, "popular.db")
THRESHOLD = 0.80  # cosine 相似度阈值，低于则不计入热门榜

_lock = threading.Lock()
_template_vecs = None  # {template_id: vec}


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """建表 + 灌入模板（count 缺省 0，已存在则跳过）。"""
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS template_hits ("
            "template_id TEXT PRIMARY KEY, question_text TEXT, count INTEGER DEFAULT 0)"
        )
        for t in TEMPLATES:
            c.execute(
                "INSERT OR IGNORE INTO template_hits(template_id, question_text, count) "
                "VALUES (?, ?, 0)",
                (t["id"], t["text"]),
            )


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _ensure_template_vecs():
    global _template_vecs
    if _template_vecs is not None:
        return
    with _lock:
        if _template_vecs is not None:
            return
        vecs = rag.embed([t["text"] for t in TEMPLATES])
        _template_vecs = {t["id"]: v for t, v in zip(TEMPLATES, vecs)}


def record(question: str):
    """把 question 归到最近模板并计数。容错：任何异常静默忽略。"""
    if not (question or "").strip():
        return
    try:
        _ensure_template_vecs()
        qv = rag.embed([question])[0]
        best_id, best_sim = None, -1.0
        for tid, tv in _template_vecs.items():
            sim = _cosine(qv, tv)
            if sim > best_sim:
                best_id, best_sim = tid, sim
        if best_id is None or best_sim < THRESHOLD:
            return
        with _conn() as c:
            c.execute(
                "UPDATE template_hits SET count = count + 1 WHERE template_id = ?",
                (best_id,),
            )
    except Exception:
        pass


def top(n: int = 4):
    """按 count 倒序取 n 条模板。返回 list[{id, text, domain}]。"""
    by_id = {t["id"]: t for t in TEMPLATES}
    try:
        init_db()
        with _conn() as c:
            rows = c.execute(
                "SELECT template_id, count FROM template_hits ORDER BY count DESC"
            ).fetchall()
        # count 全 0 时 SQLite 顺序不保证，回退到模板预设顺序
        if rows and any(r[1] > 0 for r in rows):
            ordered_ids = [r[0] for r in rows]
        else:
            ordered_ids = [t["id"] for t in TEMPLATES]
    except Exception:
        ordered_ids = [t["id"] for t in TEMPLATES]

    out = []
    for tid in ordered_ids:
        t = by_id.get(tid)
        if t:
            out.append({"id": t["id"], "text": t["text"], "domain": t["domain"]})
        if len(out) >= n:
            break
    return out
