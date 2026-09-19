# backend —— FastAPI 服务

## 分层

```
app/main.py      路由层。只做参数校验 / 鉴权 / 组装响应，业务逻辑下沉到模块
app/config.py    所有环境变量与路径的唯一入口
app/schemas.py   对外契约的唯一真相
app/store.py     Chroma 向量库封装
app/rag.py       embedding / 对话 / 问题扩展
app/auth.py      微信 openid → token → 额度
app/rail/        铁路乘车记录，独立子包（ADR-0007），路由挂 /rail
scripts/         一次性脚本与校验工具，入口统一 python -m scripts.<name>
```

## 硬性约定

**环境变量只在 `config.py` 里 `os.getenv`。** 其他模块一律 `from app import config` 取。
新增 LLM provider 只往 `config.PROVIDERS` 加一条 dict，不要在业务代码里写 if/else ——
所有 provider 都走 OpenAI 兼容接口。

**可变状态一律写 `config.DATA_DIR`**，不要写死 `BACKEND_DIR`。容器部署时 `DATA_DIR`
挂成一个卷，几个 sqlite（`auth.db` `changelog.db` `popular.db` `rail.db` `journey.db`）
和 `ingested.jsonl` 都在里面。

**`HTTPException` 的 `detail` 直接写中文用户文案**，例如「没有找到车次 G999。」。
小程序 `api.js` 的通用 `request()` 会把 detail 原样 `showToast` 给用户，所以这里不要写
英文或技术栈细节。

## Chroma 数据模型

同一个 collection（`freq_flyer`）里混着两种记录，靠 `meta.kind` 区分：

| kind | id 格式 | 用途 |
|---|---|---|
| `doc` | `frag-<uuid>` | 知识正文，检索结果的真正目标 |
| `alias` | `<doc_id>-alias-<j>` | AI 生成的别名问法，`parent_id` 回指正文 |

**任何 `col.get` / `col.query` 都必须带 `where={"kind": ...}` 过滤**，否则别名会污染结果。
`search()` 命中别名时要用 `parent_id` / `parent_text` 回查正文并按正文去重取最高分。

正文 id 用 uuid，**不要用 `col.count()` 派生 id** —— 集合里含别名且删除后会变小，必然撞车。

## 契约同步

改 `schemas.py` 里任何面向客户端的字段，必须同步这两处，否则线上静默不一致：

- `frontend/src/api.ts` —— 手写的 TS interface，没有自动生成
- `miniprogram/api.js` —— `rail` 下每个方法上面的注释就是契约文档

## 验证方式

**没有测试框架**（无 pytest / conftest / test_*.py）。回归验证靠两件事：

```bash
.venv/bin/python -m pyflakes app scripts     # 必须退出码 0，无任何输出
.venv/bin/python -m scripts.check_chunking   # 切分回归夹具
```

pyflakes 在 `requirements-dev.txt`（不进运行时镜像）。**改完 Python 代码先跑它**
——它是 AST 级的，不 import、不需要 API key、毫秒级，专治「调用了未定义的名字」
这类冒烟测试也看不出来的 bug（`_with_subject` 那次就是）。

它同时会报 unused import，目前全库已清零，**请保持 0 输出**，否则闸门会退化成噪音。
注意：被别处当再导出用的 import 不能删（如 `store.embed` 被 `rebuild_aliases.py` 用），
删之前先 `grep -rn "模块\.名字"` 确认。

改动检索、切分、别名这类链路时，要么补一条 scripts 校验，要么明确说明只做了人工验证
——不要声称「测试通过」。

### 离线可跑是硬约束

`app/chunking.py` **只准依赖标准库**（当前仅 `import re`）。一旦它 import 了
`app.ingest_url` 或 `app.rag`，链路上会立刻构造 OpenAI client（`rag.py:6` 在 import
时就 `OpenAI(...)`，无 key 直接抛 `OpenAIError`），回归脚本就退化成「必须联网 + 有额度
才能跑」。新增纯逻辑模块时沿用这个切法。

反过来说：`app/store.py` 这类必然要 import `app.rag` 的模块，做不了离线夹具，
它们的兜底就是 pyflakes。

### 新增回归断言，先确认它会红

`check_chunking.py` 的同块断言扫 `(600, 1000, 1500, 2500)` 多个块大小，不是只测线上值
——最初只测线上值时夹具「通过」了，换旧算法对照才发现**旧实现也通过，断言是空的**。
加任何回归断言，都要先拿有 bug 的旧代码验证它确实会失败，否则等于没加。

## 两个坑

**别名生成失败不影响入库，但会留日志。** 正文是同步写的、立即可检索；别名走后台
daemon 线程，进程关停时可能来不及生成。这是有意的取舍——**别名丢了不是黑洞**：

```bash
python -m scripts.check_aliases              # 只读覆盖率报告，不调 AI、不花钱
python -m scripts.check_aliases --backfill   # 只给缺别名的正文补生成
```

覆盖率由库里 alias 的 `parent_id` 反查（`store.docs_missing_aliases()`），不建账本，
补齐即自动消失。动别名链路后跑一下报告确认，不要靠「没报错」判断成功。

注意 `ingest_url.generate_aliases` **会抛异常**（不是返回 `[]`），调用方必须显式处理
——以前它吞异常，害得入库缺别名无人知晓、`rebuild_aliases` 的 429 退避从未触发。

**`.venv/` 在仓库里。** 全文搜索必须 `-not -path "*/.venv/*"`，否则会被 80 万行第三方
代码淹没（`wc -l` 全目录是 169 万行，其中源码只有 3.8k）。
