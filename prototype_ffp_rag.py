#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常旅客 RAG —— 抛弃式原型 (PROTOTYPE — 用完即弃，勿进 main)
=========================================================
目的：验证「提问 → 检索 → 拼上下文 → 生成」整条 RAG 链路"感觉对不对"。
形态：交互式终端 REPL，每轮完整打印【检索片段+相似度】【拼装上下文】【LLM 回答】。

一条命令启动：
    export LLM_API_KEY=你的key        # 智谱 GLM: https://open.bigmodel.cn
    python3 prototype_freq_flyer_rag.py

Provider 可用环境变量切换（默认智谱 GLM，OpenAI 兼容）：
    LLM_PROVIDER=zhipu | openai | qwen   (默认 zhipu)
所有 provider 都走 OpenAI 兼容 SDK，只是 base_url / 模型名不同。
"""
import os
import sys
import glob

import numpy as np

try:
    from openai import OpenAI
except ImportError:
    sys.exit("缺少依赖，请先运行: pip install -r requirements-prototype.txt")

# ---- provider 配置（全部 OpenAI 兼容）------------------------------------
PROVIDERS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "chat_model": "glm-4-flash",          # 免费
        "embed_model": "embedding-3",
    },
    "openai": {
        "base_url": None,                      # 官方默认
        "chat_model": "gpt-4o-mini",
        "embed_model": "text-embedding-3-small",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "embed_model": "text-embedding-v3",
    },
}

PROVIDER = os.getenv("LLM_PROVIDER", "zhipu")
if PROVIDER not in PROVIDERS:
    sys.exit(f"未知 LLM_PROVIDER={PROVIDER}，可选: {', '.join(PROVIDERS)}")
CFG = PROVIDERS[PROVIDER]

API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
if not API_KEY:
    sys.exit(f"请设置环境变量 LLM_API_KEY（当前 provider={PROVIDER}）。\n"
             f"智谱注册拿 key: https://open.bigmodel.cn")

client = OpenAI(api_key=API_KEY, base_url=CFG["base_url"])

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")
TOP_K = 4


# ---- 语料加载 ------------------------------------------------------------
def load_corpus():
    """每个 .md 文件 = 一个整段 chunk。文件头 'domain:' / 'source:' 作元数据。"""
    chunks = []
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.md"))):
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
        chunks.append({"domain": domain, "source": source, "text": body.strip()})
    return chunks


def embed(texts):
    """批量 embed，返回 numpy 数组 (n, d)。"""
    resp = client.embeddings.create(model=CFG["embed_model"], input=texts)
    return np.array([d.embedding for d in resp.data], dtype=np.float32)


def cosine(q, mat):
    q = q / (np.linalg.norm(q) + 1e-9)
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    return mat @ q


# ---- 检索 + 生成 ---------------------------------------------------------
def retrieve(query, chunks, embeds):
    qv = embed([query])[0]
    scores = cosine(qv, embeds)
    order = np.argsort(-scores)[:TOP_K]
    return [(float(scores[i]), chunks[i]) for i in order]


SYSTEM_PROMPT = (
    "你是常旅客（里程/积分/信用卡/酒店）领域的助手。"
    "只能根据下面提供的【资料】回答，不得编造。"
    "若资料中没有相关信息，请明确说『提供的资料里没有相关信息』。"
    "涉及用户个人账户时，请引用【模拟个人数据】。回答用中文，简洁。"
)


def generate(query, retrieved):
    context = "\n\n".join(
        f"[资料{i+1} | {c['domain']}/{c['source']}]\n{c['text']}"
        for i, (_, c) in enumerate(retrieved)
    )
    resp = client.chat.completions.create(
        model=CFG["chat_model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"【资料】\n{context}\n\n【问题】{query}"},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip(), context


# ---- REPL ----------------------------------------------------------------
def main():
    print(f"== 常旅客 RAG 原型 ==  provider={PROVIDER} "
          f"chat={CFG['chat_model']} embed={CFG['embed_model']}")
    print("加载语料并 embedding...", end="", flush=True)
    chunks = load_corpus()
    embeds = embed([c["text"] for c in chunks])
    print(f" 完成，共 {len(chunks)} 段。输入问题（q 退出）。\n")

    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.lower() in ("q", "quit", "exit"):
            break
        if not query:
            continue

        retrieved = retrieve(query, chunks, embeds)

        print("\n── 检索到 top-{} 片段 ──".format(TOP_K))
        for score, c in retrieved:
            preview = c["text"].replace("\n", " ")[:60]
            print(f"  [{score:.3f}] ({c['domain']}/{c['source']}) {preview}...")

        answer, context = generate(query, retrieved)

        print("\n── 拼装的上下文（{} 字）──".format(len(context)))
        print("── LLM 回答 ──")
        print(answer)


if __name__ == "__main__":
    main()
