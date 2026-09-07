# ffp-rag —— 常旅客 RAG

一个覆盖航司里程/权益/联盟、信用卡转点、酒店积分互通的常旅客领域 RAG。
命令行原型（`prototype_ffp_rag.py`）验证链路，已包装为 FastAPI 后端（`backend/`），
供 App / 微信小程序作为前端接入。

## 沟通语言

始终用中文与我交流。

## Agent skills

### Issue tracker

任务与规格（spec/PRD）以 markdown 文件形式追踪在本仓库 `.scratch/` 下。详见 `docs/agents/issue-tracker.md`。

### Domain docs

单上下文布局：根目录 `CONTEXT.md` + `docs/adr/`（按需惰性创建）。详见 `docs/agents/domain.md`。
