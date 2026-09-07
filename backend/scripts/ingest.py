"""一次性摄入：读 corpus/*.md → embed → 写入 Chroma 持久化。
用法: python -m scripts.ingest
"""
from app import store


def main():
    n = store.ingest()
    if n == 0:
        print("未找到语料（corpus/*.md 为空）。")
        return
    print(f"已摄入 {n} 段语料到 Chroma 集合。持久化目录见 chroma_db/。")


if __name__ == "__main__":
    main()
