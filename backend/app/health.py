"""知识库体检：时效性 / 完整性(覆盖度) / 一致性(矛盾)。

- 手动触发、后台异步跑（内存任务表 + 线程）。
- 产出可执行清单（不是评分）。
- 每个检查用不同 system prompt，扮演不同角色的 AI。
"""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app import config, store
from app.rag import client

# ---- 异步任务表（内存）----
_tasks = {}
_lock = threading.Lock()


def _new_task():
    tid = uuid.uuid4().hex[:12]
    with _lock:
        _tasks[tid] = {
            "id": tid, "status": "running", "progress": "启动中…",
            "report": None, "error": None,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    return tid


def _update(tid, **kw):
    with _lock:
        if tid in _tasks:
            _tasks[tid].update(kw)


def get_task(tid):
    with _lock:
        return dict(_tasks[tid]) if tid in _tasks else None


# ---- AI 调用小工具 ----
def _ask_json(system, user, temperature=0.2):
    resp = client.chat.completions.create(
        model=config.CHAT_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except Exception:
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else {}


def _months_since(date_str):
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (datetime.now() - d).days / 30.0
    except Exception:
        return None


# ---- 检查1：时效性（角色：时效判断器）----
TIMELINESS_SYS = (
    "你是常旅客知识的时效性审核员。给你一条知识及其发布距今月数。"
    "判断它是否『可能已过时、需要重新核实』。重点：里程比例、返现比例、活动、"
    "费率这类【易变】内容，超过约 6 个月就应提醒复核；而开卡/绑定/还款等【操作步骤】相对稳定，可放宽。"
    "只输出 JSON：{\"stale\": true/false, \"reason\": \"简短原因\"}。"
)


def _check_timeliness(docs, on_progress):
    findings = []
    for i, d in enumerate(docs):
        months = _months_since(d["date"])
        if months is None:
            continue  # 无日期（种子语料）跳过
        # 只对有一定年头的才问 AI，省调用
        if months < 3:
            continue
        try:
            r = _ask_json(
                TIMELINESS_SYS,
                f"知识：{d['text'][:300]}\n发布距今：约 {months:.0f} 个月",
            )
            if r.get("stale"):
                findings.append({
                    "text": d["text"][:100],
                    "source": d["source"], "date": d["date"],
                    "months": round(months, 1),
                    "reason": r.get("reason", ""),
                    "url": d["url"],
                })
        except Exception:
            pass
        on_progress(f"时效性 {i+1}/{len(docs)}")
    return findings


# ---- 检查2：完整性/覆盖度（角色：覆盖分析器）----
BASELINE_SYS = (
    "你是常旅客领域的专家。请列出普通用户在【里程、信用卡返现、酒店积分、"
    "支付绑定、开卡还款】等方面最常问的高频问题，覆盖面要广。"
    "只输出 JSON：{\"questions\": [\"问题1\", \"问题2\", ...]}，20-30 个。"
)


def _check_completeness(on_progress):
    on_progress("完整性：生成标准问题基线…")
    data = _ask_json(BASELINE_SYS, "请生成常旅客高频问题清单。", temperature=0.4)
    questions = [q for q in data.get("questions", []) if isinstance(q, str) and q.strip()]
    gaps = []
    for i, q in enumerate(questions):
        try:
            hits = store.search(q, top_k=1)
            top = hits[0]["score"] if hits else 0.0
            # 命中分低 = 库里没有能回答这个问题的知识 = 盲区
            if top < 0.35:
                gaps.append({"question": q, "top_score": round(top, 3)})
        except Exception:
            pass
        on_progress(f"完整性 {i+1}/{len(questions)}")
    return {"total_questions": len(questions), "gaps": gaps}


# ---- 检查3：一致性/矛盾（角色：矛盾检测器）----
CONTRADICT_SYS = (
    "你是常旅客知识的矛盾审核员。给你两条知识，判断它们是否就【同一件事】给出了"
    "【互相冲突】的信息（如同一渠道返现比例不同、同一规则数值不同）。"
    "注意：讲不同事情、或只是侧重不同，不算矛盾。"
    "只输出 JSON：{\"conflict\": true/false, \"reason\": \"若冲突，指出冲突点\"}。"
)


def _cluster_by_subtopic(docs):
    """按 (domain, subtopic) 聚类，只在同簇内两两比对，避免平方爆炸。"""
    clusters = {}
    for d in docs:
        key = (d["domain"], d.get("subtopic", "") or "无")
        clusters.setdefault(key, []).append(d)
    return clusters


def _check_consistency(docs, on_progress):
    findings = []
    clusters = _cluster_by_subtopic(docs)
    # 生成所有需比对的对
    pairs = []
    for key, items in clusters.items():
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                pairs.append((items[a], items[b]))
    total = len(pairs)
    if total == 0:
        return findings

    def _one(pair):
        x, y = pair
        try:
            r = _ask_json(CONTRADICT_SYS, f"知识A：{x['text'][:250]}\n\n知识B：{y['text'][:250]}")
            if r.get("conflict"):
                return {
                    "a": x["text"][:90], "a_source": x["source"], "a_date": x["date"],
                    "b": y["text"][:90], "b_source": y["source"], "b_date": y["date"],
                    "reason": r.get("reason", ""),
                }
        except Exception:
            pass
        return None

    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(_one, pairs):
            done += 1
            on_progress(f"一致性 {done}/{total}")
            if res:
                findings.append(res)
    return findings


# ---- 编排 ----
def _run(tid):
    try:
        docs = store.all_docs()
        _update(tid, progress=f"载入 {len(docs)} 条知识，开始体检…")

        def prog(msg):
            _update(tid, progress=msg)

        timeliness = _check_timeliness(docs, prog)
        completeness = _check_completeness(prog)
        consistency = _check_consistency(docs, prog)

        report = {
            "total_docs": len(docs),
            "timeliness": timeliness,          # 过期/需复核清单
            "completeness": completeness,      # 覆盖盲区
            "consistency": consistency,        # 矛盾对
            "summary": {
                "stale_count": len(timeliness),
                "gap_count": len(completeness.get("gaps", [])),
                "conflict_count": len(consistency),
            },
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        _update(tid, status="done", progress="完成", report=report)
    except Exception as e:
        _update(tid, status="error", error=str(e))


def start_check():
    """启动一次体检，返回 task_id。"""
    tid = _new_task()
    threading.Thread(target=_run, args=(tid,), daemon=True).start()
    return tid
