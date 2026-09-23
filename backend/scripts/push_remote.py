"""把知识片段推到线上（或任意一台）后端，让两边的正文片段对齐。

用法：
    # 本地库里有、线上没有的，补推上去
    python -m scripts.push_remote --base https://ffp.hikoutei.cn --token-file /tmp/tk --from-local

    # 把 ingest_md 导出的那份 JSON 推上去（本地已用同一份入过库）
    python -m scripts.push_remote --base https://ffp.hikoutei.cn --token-file /tmp/tk \\
        --from-json /tmp/hc_frags.json

走的是管理接口 `/admin/ingest-parsed`（`app/main.py`），和管理后台点「入库」是同一条路，
只追加不删除。

**天然可重入**：每次先拉线上 `/admin/docs` 建一份正文指纹，只推线上没有的。
中途 429、断网、Ctrl-C 都不要紧，重跑一遍即可，不会重复入库。

别名不在这里管：线上收到片段后自己在后台线程生成（`store.add_fragments` 默认异步），
所以两边的别名文本不会完全相同。别名是派生数据，`search()` 命中别名后一律回查
`parent_text`，不影响答案。线上别名没跟上就在服务器上
`docker exec ffp-rag python -m scripts.check_aliases --backfill`。
"""
import argparse
import json
import sys
import time

import requests

# 一批的片段数。线上是 1 核 / mem_limit 600m 的容器，一次请求内要同步 embed
# 整批正文，推太大容易超时或被 OOM。
BATCH = 20

# 正文指纹长度。取前 N 字符即可判同——片段正文是整节原文，前 80 字撞车的概率可以忽略。
FINGERPRINT = 80

# 只有这几个字段是 `schemas.Fragment` 认的。库里读出来的 dict 还带 id，不能原样发。
FIELDS = ("domain", "subject", "subtopic", "source", "text", "url", "date")


def fetch_remote_docs(base, token):
    r = requests.get(f"{base}/admin/docs",
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if r.status_code == 401:
        raise SystemExit("线上 ADMIN_TOKEN 不匹配（401）。注意线上那套与本地 .env 里的不是同一串。")
    r.raise_for_status()
    return r.json().get("docs", [])


def load_local():
    """本地向量库里的全部正文，转成 Fragment 形状（丢掉 id，线上会自己发 uuid）。"""
    from app import store  # 局部导入：--from-json 路径不该被 chromadb/openai 拖累
    return [{k: d.get(k, "") for k in FIELDS} for d in store.all_docs()]


def load_json(path):
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    return [{k: f.get(k, "") for k in FIELDS} for f in data]


def push(base, token, frags, dry_run=False):
    remote = fetch_remote_docs(base, token)
    seen = {d["text"][:FINGERPRINT] for d in remote}
    print(f"线上现有正文 {len(remote)} 条；待推 {len(frags)} 条")

    todo = [f for f in frags if f["text"][:FINGERPRINT] not in seen]
    skipped = len(frags) - len(todo)
    if skipped:
        print(f"其中 {skipped} 条线上已有，跳过")
    if not todo:
        print("没有需要推送的片段，线上已是最新。")
        return 0
    if dry_run:
        print(f"干跑：本会推 {len(todo)} 条，分 {(len(todo) + BATCH - 1) // BATCH} 批。")
        return 0

    pushed = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        r = requests.post(
            f"{base}/admin/ingest-parsed",
            headers={"Authorization": f"Bearer {token}"},
            json={"fragments": batch},
            timeout=600,   # 整批正文要在这一个请求里同步 embed 完
        )
        if r.status_code != 200:
            print(f"\n第 {i // BATCH + 1} 批失败：HTTP {r.status_code} {r.text[:300]}")
            print(f"已成功推送 {pushed} 条。修好后直接重跑本脚本，已推的会被自动跳过。")
            raise SystemExit(1)
        body = r.json()
        pushed += body.get("added", 0)
        print(f"  批 {i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH}："
              f"+{body.get('added')} 条，线上集合共 {body.get('total')} 条向量（含别名）")
        # 线上收到后会起后台线程生成别名，隔一拍再发下一批，别让别名任务堆叠打满 1 核
        if i + BATCH < len(todo):
            time.sleep(2)
    return pushed


def main():
    ap = argparse.ArgumentParser(description="把知识片段推到线上后端（只追加，可重跑）")
    ap.add_argument("--base", required=True, help="后端地址，如 https://ffp.hikoutei.cn")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-local", action="store_true", help="数据源：本地向量库的全部正文")
    src.add_argument("--from-json", metavar="PATH", help="数据源：ingest_md --out 导出的 JSON")
    tok = ap.add_mutually_exclusive_group(required=True)
    tok.add_argument("--token", help="线上 ADMIN_TOKEN（会进 shell 历史，建议用 --token-file）")
    tok.add_argument("--token-file", help="存着线上 ADMIN_TOKEN 的文件")
    ap.add_argument("--dry-run", action="store_true", help="只算要推多少条，不真的推")
    args = ap.parse_args()

    token = args.token
    if args.token_file:
        with open(args.token_file, encoding="utf-8") as fp:
            token = fp.read().strip()
    if not token:
        raise SystemExit("token 为空。")

    base = args.base.rstrip("/")
    frags = load_local() if args.from_local else load_json(args.from_json)
    if not frags:
        raise SystemExit("数据源里没有片段。")

    pushed = push(base, token, frags, args.dry_run)
    if pushed:
        final = fetch_remote_docs(base, token)
        print(f"\n完成：本次推送 {pushed} 条，线上现有正文 {len(final)} 条。")
        print("别名由线上后台生成，稍后用 /health 的 chunks 数确认；"
              "偏少就在服务器上 docker exec ffp-rag python -m scripts.check_aliases --backfill")


if __name__ == "__main__":
    sys.exit(main())
