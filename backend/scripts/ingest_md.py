"""把 `corpus/hotel_cards/` 的结构化 markdown 语料切片并入本地向量库。

用法：
    python -m scripts.ingest_md                      # 干跑，只报告
    python -m scripts.ingest_md --out /tmp/f.json    # 干跑 + 导出 fragments
    python -m scripts.ingest_md --out /tmp/f.json --local   # 真正写本地库

**和 `scripts/ingest.py` 完全不同**：那个会 `delete_collection` 全量重建
（只给最早那 10 条种子语料用，跑一次抹掉所有 URL 摄入的知识）；这个只追加，
走 `store.add_fragments()`，与管理后台的摄入是同一条路。

`--out` 导出的 JSON 是「线上与本地一致」的载体：本地入库和
`scripts/push_remote.py` 推线上用**同一份文件**，两边正文逐字相同，
不存在各切一遍的漂移。
"""
import argparse
import json
import os
import re
import sys

from app.corpus_md import split_sections

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
DEFAULT_DIR = os.path.join(REPO_ROOT, "corpus", "hotel_cards")

# 语料 README 声明的时效基准。这批资料没有原文 URL，date 是它唯一的时效信息，
# 前端来源标签会展示，半年后该重新调研。
CORPUS_DATE = "2026-09-21"

# 每份文件的元数据。`subject_rules` 存在时，逐节用正则从章标题里抠更精确的主体，
# 抠不到才回落到 `subject`——04 有四十多个银行章节，共用一个主体会让别名生成
# 和检索都分不清是哪家行。
FILES = [
    {"file": "01_marriott_bonvoy.md", "domain": "hotel",
     "subject": "万豪旅享家", "source": "语料-万豪Bonvoy-玩法资料"},
    {"file": "02_ihg_one_rewards.md", "domain": "hotel",
     "subject": "IHG优悦会", "source": "语料-IHG优悦会-玩法资料"},
    {"file": "03_hilton_honors.md", "domain": "hotel",
     "subject": "希尔顿荣誉客会", "source": "语料-希尔顿Honors-玩法资料"},
    {"file": "04_cn_creditcards_products.md", "domain": "credit_card",
     "subject": "中国大陆信用卡", "source": "语料-中国信用卡-产品全景",
     "subject_rules": [r"([一-龥]{2,6}银行)", r"(美国运通)"]},
    {"file": "05_cn_creditcards_playbook.md", "domain": "credit_card",
     "subject": "中国大陆信用卡", "source": "语料-中国信用卡-玩法方法论"},
]

# 小节标题的前导编号：`1.1 ` `一、` `第3项：`。subtopic 是给人看的分类标签，
# 带着编号既占长度又没信息。
_NUM_PREFIX = re.compile(r"^\s*(?:第?\d+(?:\.\d+)*\s*[.、：:]?|[一二三四五六七八九十]+\s*[、.．])\s*")


def _subject_of(cfg, sec):
    """逐节定主体：先拿章标题（level-2 的节本身就是章）试 subject_rules。"""
    for pat in cfg.get("subject_rules", []):
        m = re.search(pat, sec["h2"] or sec["title"])
        if m:
            return m.group(1)
    return cfg["subject"]


def _subtopic_of(sec):
    return _NUM_PREFIX.sub("", sec["title"])[:20]


def build_fragments(base_dir):
    """读配置里的每份文件 → 切片 → 组装成 `schemas.Fragment` 形状的 dict。"""
    frags = []
    for cfg in FILES:
        path = os.path.join(base_dir, cfg["file"])
        if not os.path.exists(path):
            raise SystemExit(f"语料文件不存在：{path}")
        with open(path, encoding="utf-8") as fp:
            text = fp.read()
        secs = split_sections(text, head=cfg["subject"])
        for sec in secs:
            frags.append({
                "domain": cfg["domain"],
                "subject": _subject_of(cfg, sec),
                "subtopic": _subtopic_of(sec),
                "source": cfg["source"],
                "text": sec["text"],
                "url": "",
                "date": CORPUS_DATE,
            })
        print(f"  {cfg['file']}: {len(secs)} 片")
    return frags


def report(frags):
    lens = [len(f["text"]) for f in frags]
    print(f"\n共 {len(frags)} 片，正文合计 {sum(lens)} 字符，"
          f"最长 {max(lens)}，最短 {min(lens)}，中位 {sorted(lens)[len(lens) // 2]}")
    subjects = {}
    for f in frags:
        subjects[f["subject"]] = subjects.get(f["subject"], 0) + 1
    top = sorted(subjects.items(), key=lambda kv: -kv[1])[:10]
    print("主体分布（前 10）：" + "、".join(f"{k}×{v}" for k, v in top)
          + f"（共 {len(subjects)} 个主体）")


def check_duplicates(frags):
    """报告与库中现有知识高度相似的片段。只报告不拦截——这批语料更完整更权威，
    真要清理也该是人在控制台上比对后决定删哪一条。"""
    from app import store
    dups = store.find_duplicates([f["text"] for f in frags])
    hits = [(f, d) for f, d in zip(frags, dups) if d]
    print(f"\n疑似重复（相似度 ≥0.90）：{len(hits)} 片")
    for f, d in hits[:10]:
        print(f"  {d['score']:.3f} 新[{f['subject']}] ↔ 旧[{d['source']}] {d['text'][:40]}…")
    if len(hits) > 10:
        print(f"  …另有 {len(hits) - 10} 条")


def main():
    ap = argparse.ArgumentParser(description="结构化 markdown 语料摄入（只追加，不重建）")
    ap.add_argument("dir", nargs="?", default=DEFAULT_DIR, help=f"语料目录，默认 {DEFAULT_DIR}")
    ap.add_argument("--out", help="把 fragments 导出成 JSON（线上/本地共用同一份）")
    ap.add_argument("--local", action="store_true", help="真正写入本地 chroma（默认只干跑）")
    ap.add_argument("--no-aliases", action="store_true", help="跳过别名生成（事后用 check_aliases --backfill 补）")
    args = ap.parse_args()

    print(f"读取语料：{args.dir}")
    frags = build_fragments(args.dir)
    report(frags)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fp:
            json.dump(frags, fp, ensure_ascii=False, indent=1)
        print(f"\n已导出 {len(frags)} 片 → {args.out}")

    if not args.local:
        print("\n干跑结束（未写库）。确认无误后加 --local 入本地库。")
        return

    from app import store
    check_duplicates(frags)
    # 同步生成别名：~150 次 LLM 调用、内部 6 并发。不走默认的后台 daemon 线程，
    # 那样脚本一退出就可能把没跑完的别名丢了（见 backend/CLAUDE.md「两个坑」）。
    print(f"\n写入本地向量库（别名{'跳过' if args.no_aliases else '同步生成，请耐心等'}）…")
    added, total = store.add_fragments(
        frags, with_aliases=not args.no_aliases, async_aliases=False)
    print(f"已写入 {added} 条知识，集合现有向量 {total} 条（含别名）。")
    print("验收：python -m scripts.check_aliases")


if __name__ == "__main__":
    sys.exit(main())
