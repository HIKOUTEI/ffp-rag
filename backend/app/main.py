"""FastAPI 入口：/chat（JSON）、/chat/stream（SSE）、/health。"""
import json

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import config, rag, store, ingest_url, popular, changelog, auth
from app import health as health_mod
from app.schemas import (
    ChatRequest, ChatResponse, Source,
    ParseUrlRequest, ParseUrlResponse, Fragment,
    IngestParsedRequest, IngestParsedResponse, UpdateDocRequest,
    ConversationRequest, ConversationResponse,
    PopularQuestion, PopularQuestionsResponse,
    LoginRequest, LoginResponse,
    CorrectionRequest, ResolveCorrectionRequest,
)

app = FastAPI(title="常旅客 RAG 后端", version="0.1.0")

# 只把「足够相关」的结果作为来源展示：低分是检索凑数的、AI 并未采用。
# 若都不相关（答案会是「资料里没有」），来源应为空而非挂一堆无关低分项。
SOURCE_MIN = 0.45

# 开发期 CORS 全开，生产收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_ready():
    if not config.API_KEY:
        raise HTTPException(500, "未设置 LLM_API_KEY，请在 .env 中配置。")
    try:
        col = store.get_collection()
        if col.count() == 0:
            raise HTTPException(500, "向量库为空，请先运行: python -m scripts.ingest")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "向量库未初始化，请先运行: python -m scripts.ingest")


def _require_admin(authorization: str):
    """校验管理员令牌。Header 形如 'Bearer <token>' 或直接 <token>。"""
    if not config.ADMIN_TOKEN:
        raise HTTPException(500, "服务未配置 ADMIN_TOKEN，管理接口不可用。")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != config.ADMIN_TOKEN:
        raise HTTPException(401, "未授权：ADMIN_TOKEN 不匹配。")


def _source_dict(r):
    """检索结果 → 前端来源标签。带 doc_id 是为了让用户报错时能指回库中知识（ADR-0005）。"""
    return {"domain": r["domain"], "source": r["source"], "score": r["score"],
            "url": r.get("url", ""), "date": r.get("date", ""),
            "doc_id": r.get("doc_id", "")}


@app.get("/health")
def health():
    ok = config.API_KEY is not None
    try:
        count = store.get_collection().count()
    except Exception:
        count = 0
    return {"status": "ok" if ok and count else "not_ready",
            "provider": config.PROVIDER, "chunks": count}


@app.post("/auth/login", response_model=LoginResponse)
def auth_login(req: LoginRequest):
    """小程序登录：code → openid → 签发 token。"""
    token = auth.login(req.code)
    return LoginResponse(token=token)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, authorization: str = Header(None)):
    auth.require_user_with_quota(authorization)
    _check_ready()
    retrieved = store.search(req.question, req.top_k)
    answer = rag.generate(req.question, retrieved)
    sources = [Source(**_source_dict(r)) for r in retrieved]
    return ChatResponse(answer=answer, sources=sources)


@app.post("/chat/conversation", response_model=ConversationResponse)
def chat_conversation(req: ConversationRequest, authorization: str = Header(None)):
    """多轮对话：改写追问→检索→带历史生成。messages 最后一条为用户最新问题。"""
    auth.require_user_with_quota(authorization)
    _check_ready()
    if not req.messages:
        raise HTTPException(422, "messages 不能为空。")
    latest = req.messages[-1].content
    history = [{"role": m.role, "content": m.content} for m in req.messages[:-1]]
    # 1) 追问改写成完整问题
    rewritten = rag.rewrite_query(history, latest)
    # 2) 智能检索：命中低时用 AI 扩展问法再检索（不影响答案来源，仍只依据库内容）
    retrieved, expanded = store.search_smart(rewritten, req.top_k)
    # 3) 带历史生成
    answer = rag.generate_with_history(history, latest, retrieved)
    # 只把「足够相关」的结果作为来源展示：低分结果是检索凑数的、AI 并未采用，
    # 若都不相关（答案会是「资料里没有」），来源应为空而非挂一堆无关低分项。
    sources = [Source(**_source_dict(r)) for r in retrieved if r["score"] >= SOURCE_MIN]
    popular.record(latest)
    return ConversationResponse(answer=answer, sources=sources, rewritten=rewritten)


@app.post("/chat/conversation/stream")
def chat_conversation_stream(req: ConversationRequest, authorization: str = Header(None)):
    """多轮 + 追问改写 + SSE 流式。事件序列：rewritten → sources → delta* → done。"""
    auth.require_user_with_quota(authorization)
    _check_ready()
    if not req.messages:
        raise HTTPException(422, "messages 不能为空。")
    latest = req.messages[-1].content
    history = [{"role": m.role, "content": m.content} for m in req.messages[:-1]]
    rewritten = rag.rewrite_query(history, latest)
    # 与非流式一致：命中低时用 AI 扩展问法再检索
    retrieved, _expanded = store.search_smart(rewritten, req.top_k)

    def event_gen():
        yield f"event: rewritten\ndata: {json.dumps({'text': rewritten}, ensure_ascii=False)}\n\n"
        # 与非流式一致：只推送足够相关的来源，避免展示 AI 未采用的低分项
        sources = [_source_dict(r) for r in retrieved if r["score"] >= SOURCE_MIN]
        yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"
        for delta in rag.generate_with_history_stream(history, latest, retrieved):
            yield f"event: delta\ndata: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    popular.record(latest)
    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/popular-questions", response_model=PopularQuestionsResponse)
def popular_questions(n: int = 4):
    """热门问题模板 top n，供小程序首屏空状态展示。"""
    items = popular.top(n)
    return PopularQuestionsResponse(
        questions=[PopularQuestion(**it) for it in items]
    )


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, authorization: str = Header(None)):
    auth.require_user_with_quota(authorization)
    _check_ready()
    retrieved = store.search(req.question, req.top_k)

    def event_gen():
        # 1) 先推送来源
        sources = [_source_dict(r) for r in retrieved]
        yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"
        # 2) 逐段推送回答
        for delta in rag.generate_stream(req.question, retrieved):
            yield f"event: delta\ndata: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
        # 3) 结束
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ---- 纠错记录 ----

@app.post("/feedback/correction")
def report_correction(req: CorrectionRequest, authorization: str = Header(None)):
    """用户给一条 AI 回答报错。快照由前端上传（ADR-0005）。
    走独立的报错日额度，不消耗提问次数。"""
    openid = auth.require_user_with_feedback_quota(authorization)
    changelog.record_correction(
        question=req.question, rewritten=req.rewritten, answer=req.answer,
        doc_ids=req.doc_ids, sources=[s.model_dump() for s in req.sources],
        note=req.note, openid=openid,
    )
    return {"ok": True}


# ---- 管理员：URL 摄入管线 ----

@app.post("/admin/parse-url")
def admin_parse_url(req: ParseUrlRequest, authorization: str = Header(None)):
    """启动异步解析（抓取+AI解析+去重检测），立即返回 task_id。前端轮询进度。
    若该 URL 已录入（规范化后库中已存在正文片段），同步硬拦，不抓取、不调 AI。"""
    _require_admin(authorization)
    if not config.API_KEY:
        raise HTTPException(500, "未设置 LLM_API_KEY。")
    existing = store.find_ingested_url(req.url)
    if existing:
        return {
            "already_ingested": True,
            "url": existing["url"],
            "source": existing["source"],
            "date": existing["date"],
            "count": existing["count"],
        }
    tid = ingest_url.parse_async(req.url)
    return {"task_id": tid}


@app.get("/admin/parse-url/{task_id}")
def admin_parse_url_status(task_id: str, authorization: str = Header(None)):
    """轮询解析进度/结果。完成时 result 含 {url,title,raw_text,fragments}。"""
    _require_admin(authorization)
    t = ingest_url.get_parse_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在。")
    # 完成时把 fragments 过一遍 Fragment 模型（校验字段），其余原样返回
    if t.get("status") == "done" and t.get("result"):
        r = t["result"]
        t = dict(t)
        t["result"] = {
            "url": r["url"], "title": r["title"], "raw_text": r["raw_text"],
            "fragments": [Fragment(**f).model_dump() for f in r["fragments"]],
        }
    return t


@app.post("/admin/ingest-parsed", response_model=IngestParsedResponse)
def admin_ingest_parsed(req: IngestParsedRequest, authorization: str = Header(None)):
    """把审阅认可的片段追加入库。"""
    _require_admin(authorization)
    if not config.API_KEY:
        raise HTTPException(500, "未设置 LLM_API_KEY。")
    added, total = store.add_fragments([f.model_dump() for f in req.fragments])
    if added:
        srcs = {f.source for f in req.fragments}
        changelog.record_change("add", "、".join(list(srcs)[:3]), f"新增 {added} 条知识")
    return IngestParsedResponse(added=added, total=total)


# ---- 管理员：知识管理（CRUD + 变更追踪）----

@app.get("/admin/docs")
def admin_list_docs(authorization: str = Header(None)):
    """列出库中所有正文知识（供管理/编辑）。"""
    _require_admin(authorization)
    return {"docs": store.all_docs()}


@app.patch("/admin/docs/{doc_id}")
def admin_update_doc(doc_id: str, req: UpdateDocRequest, authorization: str = Header(None)):
    """修改一条知识的正文（重算向量+重建别名），并记历史+日志。"""
    _require_admin(authorization)
    if not config.API_KEY:
        raise HTTPException(500, "未设置 LLM_API_KEY。")
    ok, old = store.update_doc(doc_id, req.text)
    if not ok:
        raise HTTPException(404, "知识不存在或不可编辑。")
    changelog.record_history(doc_id, old["text"], old["meta"], "update")
    changelog.record_change("update", old["meta"].get("source", doc_id),
                            f"修改：{old['text'][:30]}… → {req.text[:30]}…")
    return {"ok": True}


@app.delete("/admin/docs/{doc_id}")
def admin_delete_doc(doc_id: str, authorization: str = Header(None)):
    """删除一条知识（连别名），并记历史+日志。"""
    _require_admin(authorization)
    ok, old = store.delete_doc(doc_id)
    if not ok:
        raise HTTPException(404, "知识不存在或不可删除。")
    changelog.record_history(doc_id, old["text"], old["meta"], "delete")
    changelog.record_change("delete", old["meta"].get("source", doc_id),
                            f"删除：{old['text'][:40]}…")
    return {"ok": True}


@app.get("/admin/docs/{doc_id}/history")
def admin_doc_history(doc_id: str, authorization: str = Header(None)):
    """某条知识的历史版本。"""
    _require_admin(authorization)
    return {"history": changelog.list_history(doc_id)}


@app.get("/admin/changelog")
def admin_changelog(limit: int = 100, authorization: str = Header(None)):
    """全库变更流水。"""
    _require_admin(authorization)
    return {"changes": changelog.list_changes(limit)}


# ---- 管理员：纠错队列 ----

@app.get("/admin/corrections")
def admin_corrections(status: str = "pending", limit: int = 100,
                      authorization: str = Header(None)):
    """纠错队列。默认只列待处理；status=all 看全部。
    每条把 doc_ids 回填成当前知识正文，便于后台就地编辑。"""
    _require_admin(authorization)
    items = changelog.list_corrections(status, limit)
    for it in items:
        docs = []
        for doc_id in it["doc_ids"]:
            try:
                d = store.get_doc(doc_id)
            except Exception:
                d = None
            # 知识可能已被删除——标记缺失而不是整条报错
            docs.append(d if d else {"id": doc_id, "text": "", "missing": True})
        it["docs"] = docs
    return {"corrections": items}


@app.patch("/admin/corrections/{correction_id}")
def admin_resolve_correction(correction_id: int, req: ResolveCorrectionRequest,
                             authorization: str = Header(None)):
    """标记一条纠错记录为已处理，并记下处理备注。"""
    _require_admin(authorization)
    if not changelog.resolve_correction(correction_id, req.resolution):
        raise HTTPException(404, "纠错记录不存在或已处理。")
    return {"ok": True}


# ---- 管理员：知识库体检 ----

@app.post("/admin/health-check")
def admin_health_check(authorization: str = Header(None)):
    """启动一次知识库体检（异步），立即返回 task_id。"""
    _require_admin(authorization)
    if not config.API_KEY:
        raise HTTPException(500, "未设置 LLM_API_KEY。")
    tid = health_mod.start_check()
    return {"task_id": tid}


@app.get("/admin/health-check/{task_id}")
def admin_health_check_status(task_id: str, authorization: str = Header(None)):
    """轮询体检进度/结果。"""
    _require_admin(authorization)
    t = health_mod.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在。")
    return t
