"""结构化语料切分回归检查：对内联夹具跑 `app.corpus_md`，再对真实语料验逐字保真。

用法:
    python -m scripts.check_corpus_md

**离线、不花钱**：只 import `app.corpus_md`（→ `app.chunking`，纯标准库），
不需要 API key，也不碰向量库。

两层断言：

1. **内联夹具**盯结构规则——容器节不成片、面包屑跟着 `#` 切换、超长节每一片都带面包屑。
   夹具写在代码里而不是放 `fixtures/`，因为它要的是「刚好触发每条规则」的最小结构，
   不是真实文章；真实文章交给第二层。
2. **真实语料**（`corpus/hotel_cards/`）盯逐字保真——链接数、markdown 表格行数
   一条都不能少，未入片段的正文行不能超过那几行文档前言。
   这一层才抓得住「切分把表格拦腰截断」这类只在真数据上发作的问题。
"""
import glob
import os
import re

from app.corpus_md import MIN_LEAD_IN, MIN_LEAF, split_sections

_HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "corpus", "hotel_cards")

# 真实语料里【有意】不入库的正文行：5 份文档各自的前言（`#` 下面那段
# 「本文用于RAG知识库切块检索」「查证日期…数据来源…」）+ 两处补充资料前言
# + 05 第七章那句框架语。多于这个数就是切分真的吞了内容，必须红。
MAX_DROPPED_LINES = 10

FIXTURE = """# 文档标题
> 这是文档前言，讲的是本资料查证于哪一天、数据来自哪些官网与第三方媒体、无法交叉验证的内容
> 会怎么标注，属于元信息而不是常旅客知识，不该入库。这段刻意写得比 MIN_LEAD_IN 还长——
> 否则「容器节引导语太短」那条规则会先把它滤掉，「level-1 正文一律丢弃」这条就测了个寂寞，
> 变异测试里把 level-1 规则删掉也照样绿。写长它，这条断言才真的守着那行代码。
> （这句是凑长度的，别删——少了它前言就掉回 MIN_LEAD_IN 以下，断言又变空。）

## 一、容器章
这一段是章节引导语，很短，不该单独成片。

### 1.1 子节甲
子节甲的正文，里面有个具体比例 3:1，长度足够过叶子节的下限，应当成片。

### 1.2 短叶子
短叶子的正文只有这么一句话，但刚好过了下限，必须留住。

## 二、独立章
独立章自带正文、下面没有子节，应当自成一条片段，内容长度足够。

# 第二部分：换了一级标题

## 三、后半章
这也是条短引导语，同样不该成片。

### 3.1 超长子节
""" + "".join(f"第{i}段正文，用来把这一节撑过软上限，好验证切出来的每一片都还带着面包屑。\n"
              for i in range(80))


def _check_fixture():
    """内联夹具：逐条盯结构规则。返回 (通过?, 失败原因列表)。"""
    secs = split_sections(FIXTURE, head="测试主体")
    by_title = {s["title"]: s for s in secs}
    bad = []

    def want(cond, msg):
        if not cond:
            bad.append(msg)

    want("这是文档前言" not in "\n".join(s["text"] for s in secs),
         "文档前言（level-1 正文）本该丢弃，却进了片段")
    want("一、容器章" not in by_title,
         f"容器章的引导语只有十几字符（< MIN_LEAD_IN={MIN_LEAD_IN}），本该丢弃却成了片段")
    want("一、容器章" in by_title.get("1.1 子节甲", {}).get("breadcrumb", ""),
         "容器章的标题本该出现在子节的面包屑里，丢了主体上下文")
    want("1.2 短叶子" in by_title,
         f"短叶子正文过了 MIN_LEAF={MIN_LEAF}，本该保留却被丢弃")
    want("二、独立章" in by_title,
         "`##` 自带正文且无子节时本该自成片段")
    want("第二部分：换了一级标题" in by_title.get("3.1 超长子节", {}).get("breadcrumb", ""),
         "文件中途换了 `#`，后续片段的面包屑没跟着换")
    want("三、后半章" in by_title.get("3.1 超长子节", {}).get("breadcrumb", ""),
         "子节面包屑里丢了它所属的 `##` 章")
    want("第二部分：换了一级标题" not in by_title.get("1.1 子节甲", {}).get("breadcrumb", ""),
         "前半部分的片段串进了后面才出现的一级标题")
    want(all(s["text"].startswith("【测试主体｜") for s in secs),
         "head 参数没有替换掉面包屑里的文档标题")

    # 超长节：切成多片，且**每一片**都带完整面包屑
    parts = [s for s in secs if s["title"] == "3.1 超长子节"]
    want(len(parts) >= 2, "超长节没有被 split_text 切开")
    want(len({p["breadcrumb"] for p in parts}) == 1
         and all(p["text"].startswith(p["breadcrumb"] + "\n") for p in parts),
         "超长节切出的片段没有每一片都带面包屑（只有第一片带 = 后续片主体全丢）")
    return not bad, bad


def _check_corpus():
    """真实语料：逐字保真。返回 (通过?, 失败原因列表)。"""
    paths = sorted(glob.glob(os.path.join(CORPUS_DIR, "0[1-9]*.md")))
    if not paths:
        return True, [f"（跳过：{CORPUS_DIR} 下没有语料）"]

    bad, kept_lines, n_frag = [], set(), 0
    src_links = src_rows = 0
    dropped = []
    for p in paths:
        raw = open(p, encoding="utf-8").read()
        src_links += len(re.findall(r"https?://", raw))
        src_rows += len(re.findall(r"^\s*\|", raw, re.M))
        secs = split_sections(raw)
        n_frag += len(secs)
        for s in secs:
            kept_lines.update(ln.strip() for ln in s["body"].split("\n"))

    frag_links = frag_rows = 0
    for p in paths:
        for ln in open(p, encoding="utf-8").read().split("\n"):
            s = ln.strip()
            if not s or s.startswith("#") or s == "---":
                continue
            if s in kept_lines:
                frag_links += len(re.findall(r"https?://", s))
                frag_rows += 1 if s.startswith("|") else 0
            else:
                dropped.append((os.path.basename(p), s))

    print(f"  · {len(paths)} 份语料 → {n_frag} 片")
    if frag_links != src_links:
        bad.append(f"链接丢失：原文 {src_links} 个 → 片段 {frag_links} 个")
    else:
        print(f"  ✓ {src_links} 个来源链接全部保留")
    if frag_rows != src_rows:
        bad.append(f"表格行丢失：原文 {src_rows} 行 → 片段 {frag_rows} 行（切分把表格截断了？）")
    else:
        print(f"  ✓ {src_rows} 行 markdown 表格全部保留")
    if len(dropped) > MAX_DROPPED_LINES:
        bad.append(f"未入片段的正文行 {len(dropped)} 条，超过允许的 {MAX_DROPPED_LINES} 条")
    else:
        print(f"  ✓ 未入片段的正文行 {len(dropped)} 条（上限 {MAX_DROPPED_LINES}），均为文档前言：")
    for f, s in dropped[:MAX_DROPPED_LINES + 2]:
        print(f"      {f}  {s[:60]}")
    return not bad, bad


def main():
    ok = True
    for name, fn in (("内联夹具（结构规则）", _check_fixture),
                     ("真实语料（逐字保真）", _check_corpus)):
        print(f"\n{'=' * 60}\n{name}")
        passed, msgs = fn()
        if passed:
            for m in msgs:
                print(f"  {m}")
            print("  通过")
        else:
            ok = False
            for m in msgs:
                print(f"  ✗ {m}")
    if not ok:
        raise SystemExit("\n有断言未通过，见上面的 ✗。")
    print("\n全部通过。")


if __name__ == "__main__":
    main()
