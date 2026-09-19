"""正文切分：序号规整 + 按语义单元装箱。

从 `ingest_url` 拆出来的**纯函数**模块，只依赖标准库。这么切的理由：
`app.ingest_url` 一被 import 就会经 `app.rag` 构造 OpenAI client（`app/rag.py:6`），
没有 API key 直接抛异常。切开之后 `scripts/check_chunking.py` 才能在没装
openai/chromadb、也没有 key 的环境里跑回归。
"""
import re

# 单块目标字数。原为 1000，12000 字正文会切出 ~12 块，也就有 ~11 次切错的机会。
# 提到 2500 后降到 ~4 块；块仍足够小，不走「整篇一次过」——那样模型面对长文倾向
# 概括少抽，且 JSON 输出有被 max_tokens 截断的风险，与 PARSE_SYSTEM 的逐字保真冲突。
MAX_LEN = 2500

# 孤立序号行：整行只有一个序号，内容在下一行。公众号把序号与内容放在相邻两个
# HTML 节点时，get_text("\n") 就会切成这样；拼回去后 LLM 把 `1.\n50N` 读成小数 1.50。
# 必须带标点收尾，免得把正文里单独成行的数字（年份、金额）误当序号。
_LONE_NUM = re.compile(
    r"^\s*[（(]?\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[.．、)）]\s*$")

# 行首粘连的序号：`1.50N礼遇` 其实是「第1项：50N礼遇」。
# 点后**必须是数字**才算候选——`2.终身金卡：…` 这种点后接中文的没人会读成小数，
# 真实万豪夹具里这类有 17 行，全报出来等于把信号淹了。
_GLUED_NUM = re.compile(r"^\s*(\d{1,2})[.．](\d)")

# 递增链里两项的最大行距。`1.50N礼遇` 与 `2.75N礼遇` 之间隔着 8 行解释文字，
# 要求相邻就会漏掉；但隔了半篇文章的 `1.` 和 `2.` 显然不是一组。
_GLUE_GAP = 60

# 列表项行首。中文数字（`一、`）刻意**不**算列表项而算标题——公众号惯例是
# 中文数字分大节、阿拉伯数字分小项，把大节当列表会把整篇粘成一个不可分单元。
_LIST_ITEM = re.compile(
    r"^\s*(?:第\d{1,2}项：|[（(]?\d{1,2}\s*[.．、)）]|[-•·*※]\s*\S)")

_HEADING_CN = re.compile(r"^[一二三四五六七八九十]{1,3}\s*[、.．]")
_HEADING_MD = re.compile(r"^#{1,6}\s")


def _is_heading(line: str) -> bool:
    """是否像小节标题 / 列表引导行。切块时优先在这种行前面下刀。"""
    s = line.strip()
    if not s:
        return False
    if _HEADING_MD.match(s) or re.match(r"^【.+】$", s):
        return True
    if _HEADING_CN.match(s) and len(s) <= 40:
        return True
    # 引导行：短且以冒号收尾，如「里程碑奖励：」。它后面多半就是一组列表。
    return len(s) <= 30 and s.endswith(("：", ":"))


def _is_list_item(line: str) -> bool:
    return bool(_LIST_ITEM.match(line))


def _merge_lone_numbers(lines):
    """孤立序号行与下一行合并成 `第N项：内容`。

    写成 `第N项：` 而不是补个空格，是为了和 PARSE_SYSTEM 里的示例措辞对齐
    （「『1.50N礼遇』其实是『第1项：50N礼遇』」），让 prompt 与数据说同一种话。
    """
    out, i, n = [], 0, len(lines)
    while i < n:
        m = _LONE_NUM.match(lines[i])
        # 下一行得真有内容才合并；文末孤零零一个序号原样留着
        if m and i + 1 < n and lines[i + 1].strip():
            out.append(f"第{m.group(1)}项：{lines[i + 1].strip()}")
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return out


def find_glued_numbering(lines):
    """找出**疑似**行首粘连序号的行，只报告、不改写。返回 [(行号, 原行)]。

    `1.50N礼遇` 可能是「第1项：50N礼遇」，也可能就是小数 1.50。单看一行分不清，
    连「前导序号从 1 递增」都不足以判定——信用卡文里这样的返现比例列表很常见：

        1.5% 境内消费
        2.0% 境外消费

    按递增规则会被改写成「第1项：5%」「第2项：0%」，把正确数据毁掉。宁可漏改不可改错，
    所以这里只负责把可疑行捞出来给人看（`scripts/check_chunking.py` 会打印），
    真遇到了再针对那篇文章决定怎么办。

    判据是「前导序号构成从 1 开始的递增链」，**不要求相邻**——真实万豪夹具里
    `1.50N礼遇` 与 `2.75N礼遇` 之间隔着 8 行解释文字，按相邻找会整组漏掉。
    前导序号相同的（`4.1` / `4.2` / `4.3`）是多级编号，不是粘连，自然落不进链里。
    """
    cands = []
    for i, ln in enumerate(lines):
        m = _GLUED_NUM.match(ln)
        if m:
            cands.append((i + 1, int(m.group(1)), ln))

    hits, chain, expect = [], [], 1
    def flush():
        if len(chain) >= 2:
            hits.extend((n, ln) for n, ln in chain)
        chain.clear()

    for lineno, num, ln in cands:
        if num == expect and (not chain or lineno - chain[-1][0] <= _GLUE_GAP):
            chain.append((lineno, ln))
            expect += 1
        elif num == 1:
            flush()
            chain.append((lineno, ln))
            expect = 2
    flush()
    return hits


def normalize_numbering(text: str) -> str:
    """规整列表序号，消除 `1.` + `50N` → `1.50N` 这类粘连。

    在切分前做。PARSE_SYSTEM 已有一条专门的 anti-`1.50N` 指令但实测无效
    （见 .scratch/ingest-chunking/spec.md），prompt 兜底靠不住，改在数据层。

    只处理**孤立序号行**这一种无歧义形态；已粘在一行的交给
    `find_glued_numbering` 报告，不自动改。
    """
    return "\n".join(_merge_lone_numbers(text.split("\n")))


def _build_units(lines):
    """把行归并成「单元」。连续列表项（含各项续行）合并为一个**原子单元**，
    装箱时整组不可分——列表被块边界拦腰切断正是丢档的根因。

    返回 [{"text", "atomic", "heading"}]。
    """
    units, i, n = [], 0, len(lines)
    while i < n:
        if not _is_list_item(lines[i]):
            units.append({"text": lines[i], "atomic": False,
                          "heading": _is_heading(lines[i])})
            i += 1
            continue

        group, pending, j = [], [], i
        while j < n:
            if _is_list_item(lines[j]):
                group.extend(pending)     # 前面挂起的折行确实夹在两项之间，收编
                pending = []
                group.append(lines[j])
                j += 1
            elif _is_heading(lines[j]):
                break
            elif not lines[j].strip() and not (
                    j + 1 < n and _is_list_item(lines[j + 1])):
                break                      # 空行且后面不再有列表项，列表到此为止
            else:
                pending.append(lines[j])   # 可能是某项的折行，也可能是列表后的正文
                j += 1
        # 末尾还挂着的 pending 是「最后一项之后」的行，无从判断归属。给一点额度
        # 收编真折行，超出就退回——否则一篇没有小节标题的文章会从列表一路吞到结尾，
        # 整篇挤成一个不可分单元，等于退回「整篇不切」。
        keep = 0
        if len(pending) <= 2 and sum(len(x) for x in pending) <= 200:
            keep = len(pending)
            group.extend(pending)
        j -= len(pending) - keep
        # 紧邻在前的引导行并进来，别让列表和它的标题分家
        if units and units[-1]["heading"]:
            group.insert(0, units.pop()["text"])
        units.append({"text": "\n".join(group), "atomic": True, "heading": False})
        i = j
    return units


def _split_oversized(text: str, max_len: int):
    """超大列表组的安全阀：仍只在列表项边界下刀，绝不切进某一项内部。

    没有这道阀，一篇通篇列表的文章会挤成一个 12000 字的块，等于退回「整篇不切」。
    """
    parts, cur = [], []
    for line in text.split("\n"):
        if cur and _is_list_item(line) and sum(len(x) + 1 for x in cur) >= max_len:
            parts.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        parts.append("\n".join(cur))
    return parts


def split_text(text: str, max_len: int = MAX_LEN):
    """把长文切成若干块。`max_len` 是**软上限**：原子单元自身超限也不内部切分。

    按行（而非段落）建单元，再装箱。用 `\\n` 原样拼回，空行保留，
    所以块内文本与原文逐字一致。
    """
    if len(text) <= max_len:
        return [text]

    units = _build_units(text.split("\n"))
    chunks, cur, cur_len = [], [], 0
    for u in units:
        pieces = ([u["text"]] if not u["atomic"] or len(u["text"]) <= max_len * 2
                  else _split_oversized(u["text"], max_len))
        for t in pieces:
            # 标题前下刀，但当前块得攒够一半，免得切出一地碎块
            if cur and (cur_len + len(t) > max_len
                        or (u["heading"] and cur_len >= max_len // 2)):
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            cur.append(t)
            cur_len += len(t) + 1
    if cur:
        chunks.append("\n".join(cur))

    return [c for c in (c.strip("\n") for c in chunks) if c.strip()]
