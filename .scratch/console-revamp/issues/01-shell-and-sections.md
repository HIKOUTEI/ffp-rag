# 01 · 外壳与分区拆分

Status: resolved

见 `../spec.md`。一次做完，不分步。

## 做什么

1. `src/theme.ts` —— accent 查表，**完整类名写死**，不许拼接
2. `src/layout/Shell.tsx` + `src/layout/Sidebar.tsx`
3. `src/sections/` 五个组件，JSX 从 `App.tsx` 原样搬过来
4. `App.tsx` 改成状态容器 + `<Shell>`，状态与 handler 一行不动
5. 装 `lucide-react`，提交 `package-lock.json`
6. `CONTEXT.md` 加「控制台」词条

## 搬运时逐条核对

JSX 是搬，不是重写。每个分区搬完对一遍：

- [ ] 体检：轮询 3s、`hcProgress` 文案、四个统计徽章、三段报告、全绿时的 ✓ 文案
- [ ] 纠错：`pending`/`all` 切换、逐条展开、就地改正文、`saveCorrDoc` 连带刷新
      知识管理列表（`if (showManage) await loadManage()`）、标记已处理带备注
- [ ] 管理：变更流水的三种 action 图标与配色、知识列表编辑/取消/删除
- [ ] 规则：历史版本只读（`readOnly={rcHistoryView}`）、`rcErr` 用 `<pre>` 原样展示
      pydantic 报错、版本列表点击加载、保存备注
- [ ] 工作台：`isSubmitEnter` 输入法防误发、解析进度秒数、片段勾选与 `duplicate` 警告、
      `fixMarkdownBold`、来源按 url 去重、`isStale` 12 个月标黄

## 两个已知陷阱

**Tailwind purge**：accent 拼接会静默掉色，构建不报错。查表写死完整类名。

**`showManage` 的双重身份**：它现在既是「知识管理这块展开没有」，又被 `saveCorrDoc`
当作「要不要连带刷新」的条件。改成分区后「展开」的语义没了，但连带刷新的语义还在——
不能直接删掉这个 state，否则纠错页改完正文、切到管理页看到的是旧数据。

## Answer

做完了，六项全做。落地的文件：

```
src/theme.ts              accent 查表 + SECTION_ACCENT
src/layout/ui.tsx         Card / SectionHeader / Stat
src/layout/Sidebar.tsx    三组导航 + 底部令牌状态栏
src/layout/Shell.tsx      侧栏 + 主区 + 分区光晕 + 窄屏抽屉
src/sections/Workbench.tsx   sky 入库 ‖ violet 问答（双栏）
src/sections/Health.tsx      teal
src/sections/Corrections.tsx rose
src/sections/Manage.tsx      amber（列表 2 : 变更 1 双栏）
src/sections/Rules.tsx       emerald（编辑器 2 : 版本 1 双栏）
App.tsx                   957 → 340 行，纯状态容器
```

### 三个实现上的决定

**`showManage` 改名 `manageLoaded`。** 陷阱二的处理：展开语义没了，剩下的那半是
「这份列表加载过没有」，改名把它说清楚。不能用 `docs.length > 0` 代替——库可能真是空的，
那样纠错区改完正文就不会连带刷新了。`loadManage()` 成功时置位。

**切区加载的时机分两种。** 纠错队列每次进都刷（待处理条数是这块存在的理由，
必须是当下的）；管理和规则只在无数据时拉一次，等价于原来点「打开」的那一下，
进去后各自有刷新按钮 / 版本列表。见 `App.tsx` 的 `go()`。

**`Manage` 的 onEdit 只留一个。** 一度拆成 `onEdit`（进入编辑）+ `onEditChange`（打字），
但两者都是 `setEditing(e => ({...e, [id]: text}))`，完全同构，合并了。

### 验证

`npx tsc -b`、`npm run lint`、`npm run build` 三道全过。

产物 500.44 kB → 525.36 kB（gzip 154.02 → 162.34），多出的是 lucide 那二十几个图标。
vite 的 500 kB 警告**改动前就在响**（500.44 已经越线），不是这次引入的，
单人内部控制台不值得为此做 code-splitting。

**机器验证不了的那条：七个区的交互都没改坏，必须人工点一遍**，
按上面「搬运时逐条核对」的五行走。
