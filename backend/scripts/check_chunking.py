"""切分回归检查：对保存的正文夹具跑 `app.chunking`，验证列表不被块边界切断。

用法:
    python -m scripts.check_chunking                      # 跑全部夹具
    python -m scripts.check_chunking --capture <url> <名字>  # 抓一篇新夹具

**默认路径离线、不花钱**：只 import `app.chunking`（纯标准库），不需要 API key。
`--capture` 走 `app.ingest_url.fetch`，那条 import 链会经 `app.rag` 构造 OpenAI
client，所以需要装 requests/bs4/openai 并配好 `API_KEY`（只是构造 client，
不会真的调模型、不花钱）。

夹具放 `scripts/fixtures/<名字>.txt`，旁边可选一个 `<名字>.expect.json`：

    {"same_chunk": [["1.50N 礼遇", "2.75N 礼遇"]]}

意思是这几个关键词必须落在**同一块**里——列表被拦腰切断时这条就会红。
背景见 .scratch/ingest-chunking/spec.md。
"""
import argparse
import glob
import json
import os

from app.chunking import (MAX_LEN, _LONE_NUM, find_glued_numbering,
                          normalize_numbering, split_text)

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# 同块断言要扫过的块大小。含线上实际值 MAX_LEN，也含比列表本身还小的值，
# 后者专门盯「列表整组塞不下时也只在项边界下刀」这条。
SWEEP = (600, 1000, 1500, MAX_LEN)


def capture(url: str, name: str):
    """抓一篇文章的正文存成夹具。只抓取，不调 LLM。"""
    from app.ingest_url import fetch  # 局部导入：默认路径不该被 openai 依赖拖累

    title, text, date = fetch(url)
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    path = os.path.join(FIXTURE_DIR, f"{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已保存 {path}（{len(text)} 字）\n标题：{title}\n日期：{date or '未知'}")
    print("\n请人眼确认列表序号的排布形态，再决定要不要加 expect.json。")


def check(path: str) -> bool:
    name = os.path.basename(path)[:-4]
    raw = open(path, encoding="utf-8").read()
    text = normalize_numbering(raw)
    chunks = split_text(text)

    print(f"\n{'=' * 60}\n{name}.txt — {len(raw)} 字 → {len(chunks)} 块"
          f"（软上限 {MAX_LEN}）")
    for i, c in enumerate(chunks, 1):
        head = c.split("\n", 1)[0][:36]
        flag = "  ⚠ 超上限" if len(c) > MAX_LEN else ""
        print(f"  块 {i}: {len(c):>5} 字{flag}  首行「{head}」")

    ok = True

    # 规整后不该再有孤立序号行——有就说明 normalize_numbering 漏了一种形态
    lone = [ln for ln in text.split("\n") if _LONE_NUM.match(ln)]
    if lone:
        ok = False
        print(f"  ✗ 仍有 {len(lone)} 个孤立序号行：{lone[:5]}")
    else:
        print("  ✓ 无孤立序号行")

    # 规整生效了多少处
    n_norm = text.count("第") - raw.count("第")
    print(f"  · 序号规整改写 {max(n_norm, 0)} 处")

    # 已粘在一行的序号不自动改（会误伤 `1.5% 境内消费` 这类真小数），只报告
    glued = find_glued_numbering(text.split("\n"))
    if glued:
        print(f"  ⚠ {len(glued)} 行疑似行首粘连序号，需人眼判断是序号还是小数：")
        for lineno, ln in glued[:6]:
            print(f"      第{lineno}行  {ln.strip()[:50]}")

    exp_path = path[:-4] + ".expect.json"
    if not os.path.exists(exp_path):
        print("  · 无 expect.json，跳过同块断言")
        return ok

    exp = json.load(open(exp_path, encoding="utf-8"))
    for group in exp.get("same_chunk", []):
        # 扫多个 max_len 而不是只测线上那个值：列表被切散与否取决于边界恰好落在哪，
        # 单点测试很容易碰巧通过（改这版时就踩过：列表短的时候旧算法也能蒙对）。
        # 「任何块大小下列表都不被切散」才是真正要守住的不变量。
        bad = []
        for ml in SWEEP:
            chs = split_text(text, ml)
            hits = {kw: {i for i, c in enumerate(chs, 1) if kw in c} for kw in group}
            missing = [kw for kw, v in hits.items() if not v]
            if missing:
                ok = False
                print(f"  ✗ {group}：正文里找不到 {missing}")
                bad = None
                break
            if not set.intersection(*hits.values()):
                bad.append((ml, {kw: sorted(v) for kw, v in hits.items()}))
        if bad is None:
            continue
        if bad:
            ok = False
            ml, hits = bad[0]
            print(f"  ✗ {group} 在 max_len={ml} 下被切散："
                  + "，".join(f"{kw}→块{v}" for kw, v in hits.items()))
        else:
            print(f"  ✓ {group} 在 max_len={list(SWEEP)} 下均未被切散")
    return ok


def main():
    ap = argparse.ArgumentParser(description="切分回归检查")
    ap.add_argument("--capture", nargs=2, metavar=("URL", "NAME"),
                    help="抓一篇文章存成夹具")
    args = ap.parse_args()

    if args.capture:
        capture(*args.capture)
        return

    paths = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.txt")))
    if not paths:
        raise SystemExit(f"{FIXTURE_DIR} 下没有夹具，先用 --capture 抓一篇")

    if all([check(p) for p in paths]):
        print(f"\n{len(paths)} 份夹具全部通过。")
    else:
        raise SystemExit("\n有夹具未通过，见上面的 ✗。")


if __name__ == "__main__":
    main()
