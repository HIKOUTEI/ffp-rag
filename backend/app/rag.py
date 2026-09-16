"""核心 RAG 逻辑：embedding 与生成（从已验证的原型迁移）。"""
from openai import OpenAI

from app import config

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)


def embed(texts):
    """批量 embed，返回 list[list[float]]。"""
    resp = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


SYSTEM_PROMPT = (
    "你是常旅客（里程/积分/信用卡/酒店）领域的助手。"
    "只能根据下面提供的【资料】回答，不得编造。"
    "若资料中没有相关信息，请明确说『提供的资料里没有相关信息』。"
    "涉及用户个人账户时，请引用【模拟个人数据】。"
    "回答用中文，务必精简凝练："
    "先直接给出核心答案（保留原文的具体数字/比例/金额，不得丢失）；"
    "把『同一类』信息合并成一句（例如『无法获得A、B、C』合成一句），"
    "但不同性质的内容（如收益 vs 限制）要分开成不同要点，不要硬塞在一条里；"
    "每个要点必须主语清晰、能独立读懂（例如涉及某支付方式的限制要写明『用微信支付无法获得…』，不要省略主语）；"
    "能一两句说清就不要凑条数，最多 3 条，不写多余铺垫。"
    "【排版】请用 Markdown 输出：关键数字、比例、金额用 **加粗** 突出（如 **2.4%**）；"
    "多个要点用无序列表（- 开头）；不要用一级/二级标题，保持简短。"
)


def build_messages(query, retrieved):
    """retrieved: list[dict(domain, source, text, score)] -> chat messages。"""
    context = "\n\n".join(
        f"[资料{i+1} | {r['domain']}/{r['source']}]\n{r['text']}"
        for i, r in enumerate(retrieved)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【资料】\n{context}\n\n【问题】{query}"},
    ]


def generate(query, retrieved):
    """一次性返回完整回答。"""
    resp = client.chat.completions.create(
        model=config.CHAT_MODEL,
        messages=build_messages(query, retrieved),
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


# ---- 多轮对话 ----

REWRITE_SYSTEM = (
    "下面是一段用户与常旅客助手的对话历史，以及用户的最新一句话。"
    "请把用户最新这句话改写成一个【独立完整、可直接用于检索知识库】的问题："
    "补全省略的主语/对象（如把『那云闪付呢』补成『Pulse卡用云闪付能拿多少回赠』）。"
    "只输出改写后的问题本身，不要解释、不要加引号。"
    "若最新一句已经完整，原样输出即可。"
)


def rewrite_query(history, latest):
    """结合历史，把追问改写成独立完整问题。history: list[{role, content}]（不含最新）。"""
    if not history:
        return latest
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    resp = client.chat.completions.create(
        model=config.CHAT_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": f"【对话历史】\n{convo}\n\n【用户最新一句】{latest}"},
        ],
        temperature=0.0,
    )
    return resp.choices[0].message.content.strip() or latest


EXPAND_SYSTEM = (
    "用户的问题在知识库里没有很好命中。请把它改写成 3-4 个语义等价但表达不同的检索问法，"
    "覆盖同义词、简称、口语与书面等不同说法，帮助在知识库中找到相关内容。"
    "只输出 JSON：{\"queries\": [\"问法1\", \"问法2\", ...]}。"
)


def expand_query(question):
    """把一个问题扩展成多个等价问法（用于命中低时的检索兜底）。返回 list[str]。"""
    try:
        resp = client.chat.completions.create(
            model=config.CHAT_MODEL,
            messages=[
                {"role": "system", "content": EXPAND_SYSTEM},
                {"role": "user", "content": question},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        import json as _json
        data = _json.loads(resp.choices[0].message.content.strip())
        qs = data.get("queries", [])
        return [q.strip() for q in qs if isinstance(q, str) and q.strip()][:4]
    except Exception:
        return []


def generate_with_history(history, latest, retrieved):
    """带对话历史生成回答。history: 之前的 {role, content} 列表；latest: 最新问题。"""
    context = "\n\n".join(
        f"[资料{i+1} | {r['domain']}/{r['source']}]\n{r['text']}"
        for i, r in enumerate(retrieved)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-6:]  # 带上近几轮对话
    messages.append({
        "role": "user",
        "content": f"【资料】\n{context}\n\n【问题】{latest}",
    })
    resp = client.chat.completions.create(
        model=config.CHAT_MODEL, messages=messages, temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def generate_with_history_stream(history, latest, retrieved):
    """带对话历史的流式生成，逐段 yield token 文本。逻辑同 generate_with_history。"""
    context = "\n\n".join(
        f"[资料{i+1} | {r['domain']}/{r['source']}]\n{r['text']}"
        for i, r in enumerate(retrieved)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-6:]
    messages.append({
        "role": "user",
        "content": f"【资料】\n{context}\n\n【问题】{latest}",
    })
    stream = client.chat.completions.create(
        model=config.CHAT_MODEL, messages=messages, temperature=0.2, stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
