# 宿主机只有 python3.14，chromadb 的原生依赖在 cp314 上没有 wheel，
# 会退回源码编译并在 1 核机器上耗尽内存。锁 3.12。
FROM python:3.12-slim

WORKDIR /app

# 依赖层单独 COPY：只要 requirements.txt 没变，改代码重建时不会重装 chromadb（约 1.5G）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY corpus ./corpus

# 可变状态（三个 sqlite + ingested.jsonl）与向量库都挂在外面，见 compose
ENV DATA_DIR=/app/data \
    CHROMA_DIR=/app/chroma_db \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# --workers 1 是硬约束不是调优：额度计数与 session 存在进程本地的 sqlite，
# 多 worker 会各算各的。见 ADR-0002。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
