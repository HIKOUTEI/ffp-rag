# 01 · 别名入库改为可靠生成（不再静默丢失）

Status: done

## 问题

`store.add_fragments`（`app/store.py`）里别名走后台 daemon 线程 + `try/except: pass`：
- daemon 线程在主进程退出时被直接杀掉，别名丢失且无日志。
- AI 调用失败也被 `except: pass` 吞掉。
- 结果：批量入库后大面积缺别名（本轮实测 171 正文仅 5 别名）。

## 候选方向（待定方案）

- 别名生成失败/未完成时**落一条日志或标记**，不再静默。
- 或改为**同步生成**（入库稍慢但可靠），或入库后有**补偿任务**扫缺失并补齐。
- 提供一个「别名健康度」检查：正文数 vs 有别名的正文数。

## 验收
- 批量入库后，别名覆盖率接近 100%，缺失有日志可查。

## Comments

### 2026-09-19 · 找到「171 正文仅 5 别名」的根因：`_with_subject` 压根没定义

`app/store.py` 里 **`def _with_subject(f):` 这一行从来不存在**。函数体（原 182-188 行）
悬挂在 `find_ingested_url` 的 `return` 之后，是永远执行不到的死代码。
`git log -S"def _with_subject"` 无任何结果——自 `bdb04b4` 引入时就是坏的。

三个调用点的后果：

| 调用点 | 后果 |
|---|---|
| `store.py:196` `_build_aliases` | 在 `except: pass` 里 → 每次调用都 `NameError`，**别名 100% 静默失败** |
| `store.py:352` `update_doc` | 无保护 → `PATCH /admin/docs/{id}` 必 500 |
| `scripts/rebuild_aliases.py:46` | 一跑就崩 |

这解释了实测数据：`add_fragments` 走的正是 `_build_aliases`，所以**新入库的别名一条都没有**，
残存的 5 条应是 bug 引入前的遗留。

已修复（补回 `def`）。行为验证 4 个分支均正确：加前缀 / 主体已在前 40 字不重复加 /
无主体原样 / 缺 `subject` 键原样。

**本 issue 不关闭。** 根因修了，但这条 issue 真正要解决的是「不再静默」——
`_build_aliases` 的 `except: pass` 和 daemon 线程还在，下次换个异常一样会无声丢失。
候选方向（落日志 / 同步生成 / 补偿任务 / 覆盖率检查）依然有效。

顺带加了兜底：`requirements-dev.txt` 引入 pyflakes，全库已清到 0 输出。
这类「调用了未定义的名字」的 bug 它秒抓，而 `store.py` 因为必须 import `app.rag`
（import 时就构造 OpenAI client）做不了离线夹具，静态检查是唯一低成本兜底。

**待办：确认生产库的别名覆盖率，本地库不用重建。**

修完后实测本地 `backend/chroma_db/`：

```
集合总条数 986 = 正文 166 + 别名 820
有别名的正文 166/166 = 100%
```

看似没问题，但进一步查发现**986 条记录里没有一条 meta 带 `subject` 键**
（正文 0/166，别名 0/820）。而现有 `add_fragments` / `_build_aliases` 每次写入都必定写
`"subject": ...`。结论：**本地库的全部数据都是 `bdb04b4` 之前写的**，bug 引入后这里
没有新入库过，所以本地观察不到症状，也没有重建的必要（这些正文本就没有 subject，
重建出来的别名与现状等价，纯属白烧额度）。

issue 开头记的「171 正文仅 5 别名」应来自**生产库**（`ffp.hikoutei.cn`）——那边持续有
新知识入库，走的正是 `_build_aliases` 这条必然 `NameError` 的路径。
所以真正要做的是：**部署本次修复后，在生产库上查覆盖率，只对缺别名的正文补生成**。

`scripts/rebuild_aliases.py` 目前是「全删重建」，对生产库是杀鸡用牛刀且贵。
建议配合本 issue 的「别名健康度检查」一起做成增量补偿：先列出 `kind=doc` 里没有任何
`parent_id` 指向它的正文，只对这批调用生成。

### 2026-09-19 · 静默失败已根治，issue 关闭

生产库尚未启用任何数据，故不涉及存量修复；本地库验证完毕。

**静默失败原来有三层**，逐层拆掉：

| 位置 | 原来 | 现在 |
|---|---|---|
| `ingest_url.generate_aliases` | `except: return []` | 异常往外抛，调用方自己处理 |
| `ingest_url.generate_aliases_batch` | 逐条 `except: []` | 返回 `(results, failures)`，失败项带异常对象 |
| `store._build_aliases` | `except: pass` | 逐条落 `log.warning`（带 doc_id + source + 原因） |
| 后台线程入口 | 无 | 新增 `_build_aliases_safe`，未预期异常记全栈 |
| `store.update_doc` | 依赖上面的吞异常 | 显式兜住：正文已更新，别名失败只记日志不 500 |

**连带修好的第二个 bug**：`rebuild_aliases.gen_with_backoff` 靠捕获异常做 429 退避，
但 `generate_aliases` 把异常吞了永远返回 `[]`——**退避逻辑从上线起就没触发过**。
现在异常能抛出来了，退避才真正生效。顺手把重复的退避实现提到
`ingest_url.generate_aliases_with_retry`，两个脚本共用。

**别名健康度**：新增 `scripts/check_aliases.py`。

```
python -m scripts.check_aliases              # 只读报告，不调 AI、不花钱
python -m scripts.check_aliases --backfill   # 只给缺别名的正文补生成
```

覆盖率由库里 alias 的 `parent_id` 反查得出（`store.docs_missing_aliases()`），
**不建额外账本**——补齐后自动从缺失列表消失，不会出现「账本说补过了实际没有」。
与 `rebuild_aliases`（全删重建，改了 ALIAS_SYSTEM 时用）分工明确。

daemon 线程**保持不变**：进程关停时宁可丢别名也不拖住退出。丢了不再是黑洞，
`check_aliases --backfill` 能扫出来补。

### 验收记录

- 覆盖率报告：`166/166 (100.0%)`
- 补偿路径端到端实跑：人为删掉 `chunk-0` 的别名 → 报告准确扫出 1 条 →
  `--backfill` 走真实 AI 生成 5 条问法写回 → 复检 0 缺失，集合总数回到 986（与动手前一致）
- 失败可见性：打桩模拟三种失败（AI 全失败 / 写库失败 / 线程未预期异常），
  三种都产出带 doc_id 与原因的日志，库无污染
