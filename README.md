# ffp-rag —— 常旅客 RAG

FFP = Frequent Flyer Program（常旅客计划）。一个覆盖**航司里程/权益/联盟、信用卡积分转点、酒店会员积分**的领域问答系统，基于 RAG（检索增强生成）。

后端为 FastAPI，供未来的 App / 微信小程序作为前端接入。

## 目录结构

```
ffp-rag/
├── prototype_ffp_rag.py          # 命令行原型（验证 RAG 链路用，可留作 primary source）
├── requirements-prototype.txt
├── corpus/                       # 种子语料（10 段：三域 + 模拟个人账户）
└── backend/                      # 正式后端
    ├── app/
    │   ├── config.py             # provider 配置（zhipu/openai/qwen）+ 路径 + ADMIN_TOKEN
    │   ├── rag.py                # embed / generate / generate_stream
    │   ├── store.py              # Chroma 封装：ingest(全量重建) / add_fragments(追加) / search
    │   ├── ingest_url.py         # URL 抓取 + AI 抽取切分打标（小红书不支持）
    │   ├── schemas.py            # Pydantic 请求/响应模型
    │   └── main.py               # FastAPI 路由
    ├── scripts/ingest.py         # CLI：把 corpus 语料摄入 Chroma
    ├── corpus/                   # 后端用的语料（初始 = 复制自根 corpus）
    ├── requirements.txt
    └── .env.example
```

## 快速开始

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # 填 LLM_API_KEY 和 ADMIN_TOKEN

# 首次 / 语料更新后：把 corpus 种子语料摄入 Chroma
python -m scripts.ingest

# 起服务
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000/docs 用 Swagger 交互
```

`.env` 需要：

```
LLM_PROVIDER=zhipu                # 默认智谱 GLM（OpenAI 兼容）；可选 openai / qwen
LLM_API_KEY=...                   # 智谱 key: https://open.bigmodel.cn
ADMIN_TOKEN=一串随机密钥           # 保护 /admin/* 接口
```

## 接口

### 问答（前端调用）

| 接口 | 说明 |
|------|------|
| `POST /chat` | 返回 `{answer, sources:[{domain,source,score}]}` |
| `POST /chat/stream` | SSE 流式：先 `sources` 事件 → 逐段 `delta` → `done`（打字机效果） |
| `GET /health` | 健康检查，返回 provider 与已加载语料数 |

请求体：`{"question": "国航金卡有哪些权益？", "top_k": 4}`

### 资料摄入（管理员用，需 `Authorization` 头）

资料入口是「**给 URL → AI 抓取解析 → 人工过审 → 入库**」两步式：

```bash
# 1) 预览：抓取 + AI 解析成结构化片段，不入库
curl -X POST http://127.0.0.1:8000/admin/parse-url \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://mp.weixin.qq.com/s/xxxx"}'
# → {title, fragments:[{domain,source,text}, ...]}

# 2) 审阅（可编辑 fragments）后确认追加入库
curl -X POST http://127.0.0.1:8000/admin/ingest-parsed \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fragments":[{"domain":"airline","source":"公众号-国航","text":"..."}]}'
# → {added, total}
```

**支持的来源**：普通网页、微信公众号单篇图文文章。
**不支持**：小红书（强反爬，服务器无法直接抓取，接口会返回明确提示）。

## 验证清单

启动后在 `/docs` 试四类问题，确认 RAG 链路：

1. **单域**：「国航金卡有哪些权益？」→ sources 只含 airline。
2. **跨域**：「我招行信用卡积分怎么转成航司里程？」→ sources 含 credit_card + airline。
3. **个人账户**：「我现在的国航里程够换北京往返东京吗？」→ 命中 personal_account + alliance。
4. **无据**：「我的花旗信用卡有什么权益？」→ answer 明确「资料里没有」，不编造。

## 已知限制 / 后续方向

- **公众号抓取有不确定性**：链接时效、反爬、图片型文章可能抓不到或残缺。命中率低时可加「粘贴文本」降级入口。
- 未做：小红书自动抓取、AI 冲突去重、增量更新、重建空窗原子切换、多用户账户、生产级鉴权/CORS。
- `POST /chat`、语料摄入均需真实 LLM key 才能端到端运行。
