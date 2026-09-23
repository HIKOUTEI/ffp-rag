"""结构化 markdown 语料切分：按 `##` / `###` 标题切块，正文逐字保留。

与 `ingest_url.parse()` 的分工：那条管线面对的是公众号抓下来的一坨无结构纯文本，
只能让 LLM 重新抽取改写；这里的语料（`corpus/hotel_cards/`）本身就按
`#` 文档 / `##` 章 / `###` 子节 写好了，标题即天然切点。绕开 AI 那一道，
原文的来源链接、「查证日期」、【未证实】标注才不会在改写中蒸发。

和 `app/chunking.py` 一样**只依赖标准库**（这里多一个 `app.chunking`，它本身也是纯标准库）。
理由见 backend/CLAUDE.md「离线可跑是硬约束」：一旦链路上 import 了 `app.rag`，
回归脚本就要求有 API key 才能跑。
"""
import re

from app.chunking import MAX_LEN, split_text

# 叶子节（下面没有子节）的正文下限。滤掉零散分隔线，但留住真·短知识——
# 04 的「银翼白金卡」整节只有 39 字符（「未获得独立权益页面，【未证实】…」），
# 阈值定 40 会把它整条吞掉。
MIN_LEAF = 20

# 容器节（下面还有子节）的引导语下限。`## 七、风险与合规边界` 下面那句
# 「这一部分是本文档的安全护栏」是章节框架语不是知识，单独成片只会污染检索；
# 但万一哪天某章的引导语本身就是大段正文，也不能白丢，故留这道口子。
MIN_LEAD_IN = 200

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _breadcrumb(head, doc_title, h1, h2, title):
    """标题路径行：`【主体｜章 / 节 / 子节】`。缺失的层级直接略过，不留空分隔符。

    `h1 == doc_title` 时略掉它——文档标题已经由 `head` 代表，再拼一遍就是
    「万豪旅享家｜万豪旅享家 Marriott Bonvoy 完整玩法资料 / …」。只有文件中途
    换过 `#`（04 的「第一部分」）时，h1 才带信息量。
    """
    parts = [p for p in (h1 if h1 != doc_title else "", h2, title) if p]
    return f"【{head}｜{' / '.join(parts)}】" if parts else f"【{head}】"


def split_sections(text, max_len=MAX_LEN, head=None):
    """把一份结构化 markdown 切成片段。

    `head` 是面包屑最前面的主体名，默认取文档标题（第一个 `#`）。摄入脚本会传更短的
    品牌名（「万豪旅享家」而不是「万豪旅享家 Marriott Bonvoy 完整玩法资料」）——
    面包屑每条片段都带，冗余词会稀释 embedding。

    返回 list[dict(h1, h2, title, level, breadcrumb, body, text)]：
      - `body` 是该节正文，与原文逐字一致；
      - `text` 是 `breadcrumb` + 换行 + `body`，即最终入库的片段正文。

    规则（全部由 `corpus/hotel_cards/` 的实际结构定）：
      - `#` 可在文件中途切换（04 的「第一部分…第五部分」），面包屑跟着变；
      - `#` 自己的正文一律丢弃——那是语料自述的元信息（「本文用于RAG知识库切块检索」
        「本文数据查证于…」），不是常旅客知识；
      - **容器节**（下面还有更深一级的子节）默认只贡献面包屑、不出片段，
        引导语长过 `MIN_LEAD_IN` 才另当别论；
      - **叶子节**正文过 `MIN_LEAF` 就成片，`##` 自带正文且无子节的（05 的八章）也算叶子；
      - 超长节交给 `chunking.split_text`，**每一片都重新带上面包屑**——
        否则第二片往后主体全丢，embedding 和喂给 LLM 的上下文都会失真。
    """
    raw, doc_title = _scan(text)
    out = []
    for i, sec in enumerate(raw):
        body = "\n".join(sec["body"]).strip()
        if sec["level"] == 1 or not body:
            continue
        has_child = i + 1 < len(raw) and raw[i + 1]["level"] > sec["level"]
        if len(body) < (MIN_LEAD_IN if has_child else MIN_LEAF):
            continue
        crumb = _breadcrumb(head or doc_title, doc_title,
                            sec["h1"], sec["h2"], sec["title"])
        for part in split_text(body, max_len):
            out.append({
                "h1": sec["h1"], "h2": sec["h2"], "title": sec["title"],
                "level": sec["level"], "breadcrumb": crumb,
                "body": part, "text": f"{crumb}\n{part}",
            })
    return out


def _scan(text):
    """按标题扫成 `(list[dict(h1, h2, title, level, body)], 文档标题)`，不做任何取舍。"""
    doc_title, h1, h2 = "", "", ""
    raw, cur = [], None
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if not m:
            if cur is not None:
                cur["body"].append(line)
            continue

        level, title = len(m.group(1)), m.group(2).strip()
        if level == 1:
            if not doc_title:
                doc_title = title
            h1, h2 = title, ""
        elif level == 2:
            h2 = title
        # level >= 3 只开新节，不动面包屑的上层
        cur = {"h1": h1, "h2": h2 if level > 2 else "", "title": title,
               "level": level, "body": []}
        raw.append(cur)
    return raw, doc_title
