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

## 子 agent 与 workflow

**默认不启动。** 本仓库后端仅 ~3.8k 行 / 27 个 py 文件，前端与小程序各十几个文件，
绝大多数需求只碰 1~3 个文件，主会话直接 Read/Grep/Edit 更快，上下文也能留给后续追问。

### 允许启动子 agent 的三种情况

1. **跨端 fan-out 搜索**：同一个概念要同时在 `backend/` `frontend/` `miniprogram/` 里找。
   用 `Explore` agent，只收结论。注意仓库里入库了 `backend/.venv/` 和
   `miniprogram/miniprogram_npm/`，裸搜会被几十万行第三方代码淹没，搜索必须 prune 掉。
2. **契约冻结后的多端并行**：见下方「冻结线」。
3. **RAG 检索质量评测**：批量问题跑检索 + 逐条打分，天然可并行且互不依赖。
   这是本仓库唯一值得开 `Workflow` 的场景。

### 冻结线规则

跨端需求真正的瓶颈是契约（字段名、可空性、错误码），不是写代码。
禁止「规划完就把各端同时放出去」——那样每个 agent 只能各自猜一份契约，必然漂移。

```
主 agent：拆解 + 定契约（schema / endpoint / 错误码，写进 issue 01）
    ↓   ← 冻结线：backend schema 落地、endpoint 跑通
并行：frontend │ miniprogram │ iOS      # 三端目录隔离，无写冲突
```

冻结线之前串行；之后各端互不依赖才可并行。依赖关系用
`docs/agents/issue-tracker.md` 里的 `Blocked by: NN` 表达：

```
01-contract-and-schema.md      (无依赖)
02-backend-endpoint.md         Blocked by: 01
03-miniprogram-page.md         Blocked by: 02   ┐
04-frontend-admin.md           Blocked by: 02   ├ 这几个才并行
05-ios-....md                  Blocked by: 02   ┘
```

### 触发线

并行只在 **单端改动 ≥3 个文件，且至少两端要动** 时才回本。
改一个字段这种，agent 启动开销 + 读多份报告，比串着改 40 行代码慢。

注：iOS 端目前只存在于 `CONTEXT.md` 和 spec 里，仓库内无任何 Swift 代码。

## 分目录约定

各端的具体写法约定见 `backend/CLAUDE.md`、`frontend/CLAUDE.md`、`miniprogram/CLAUDE.md`，
碰到对应目录时会自动加载。
