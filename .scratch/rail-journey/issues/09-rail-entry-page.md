# 09 · 录入流程（`pages/rail-entry/`）

Status: done

Blocked by: 04, 06

负责目录：**只改 `miniprogram/pages/rail-entry/`**。不要动 `api.js`、`app.json`、
`custom-tab-bar/`、`styles/rail.wxss`、`rail-util.js`——共享地基已搭好，改了会冲突。

## 任务

整个功能的核心交互，也是这批里最复杂的一页。一句话：
**输个车次号，系统把全程停站摊开，用户点上车站、点下车站、选个日期，存。**

页面已在 `app.json` 注册（非 tab 页，由行程页 `wx.navigateTo` 进入），
只需建 `rail-entry.js / .json / .wxml / .wxss`。`rail-entry.wxss` 第一行：
`@import "/styles/rail.wxss";`

## 四步向导（单页内切换，不做多页跳转）

### 第 1 步：搜车次

- 顶部 `<t-search placeholder="输入车次号，如 G1、K551">`。
- 输入**防抖 300ms** 后调 `api.rail.searchTrains(q)` →
  `[{number, class, origin, terminal, stop_count, total_km}]`，最多 20 条。
- 结果列表每行：车次号（粗体）+ `<t-tag>` 种别（theme 用 `u.classTheme(item.class)`）+
  次行灰字「始发 → 终到 · N 站 · 全程 X km」。
- ⚠️ **29% 的车次号含 `/`**（跨线换号，如 `K551/K554`），而用户车票上只印其中一段。
  后端已走别名表：搜 `K554` 会命中 `K551/K554`。所以搜索结果里出现的车次号
  **和用户输入的不一样是正常的**，不要过滤掉、也不要「智能纠正」。
  展示时原样显示完整号 `K551/K554`。
- 空输入直接清空结果，不发请求（`api.rail.searchTrains('')` 已内置返回空数组）。
- 无结果时显示 `<t-empty description="没找到这个车次">` 并附一行小字提示：
  「可以试试去掉字母只输数字，或者用手填模式记录」+ 一个「手填」按钮（见最后一节）。

### 第 2 步：展开停站，点上车站

选中车次后 `api.rail.timetable(number)` →

```
{number, class, origin, terminal, stop_count, total_km, gtfs_version,
 stops: [{seq, station, arrival, departure, day_offset, dist_km, lat, lon}]}
```

渲染成一条**竖向时刻表**，每站一行：

```
 ●  01  北京南        ——:——  06:30      0 km
 │
 ●  02  廊坊          06:51  06:53     59 km
```

- 左侧一条竖线 + 圆点，构成路线感。第一站和最后一站的圆点加粗/变色。
- 时刻用 `u.fmtTime(arrival)` / `u.fmtTime(departure)`——
  **始发站没有到达时刻、终到站没有发车时刻，后端给的就是 `null`**，
  显示破折号是正确的，不要回填成 `00:00`。
- `day_offset > 0` 时在该行时刻后加 `u.dayTag(day_offset)`，如「05:12 +1天」。
  实测最大 +3 天（有车次跑到 `77:30:00`）。
- `dist_km` 是**自始发站起的累计营业里程**，与票面一致。
- 停站数最多可达上百，列表要能顺畅滚动；不要一次性做复杂动画。

**点选逻辑**：

1. 第一次点某站 → 设为**上车站**，该行高亮，上方提示条变成「已选上车站：X，请选择下车站」。
2. 第二次点一个 `seq` 更大的站 → 设为**下车站**，两站之间的所有行变成高亮区段。
3. 若第二次点的站 `seq` 小于等于上车站 → **重置为新的上车站**，不要报错。
4. 提示条上永远有一个「重选」按钮，清空两个选择。

选定区段后，提示条显示区段摘要：`X → Y · N 站 · Z km`，
里程 = `stops[to].dist_km - stops[from].dist_km`（前端自己算，用于即时反馈；
入库后后端会重新算一遍，以后端为准）。

### 第 3 步：填日期与备注

区段选好后，底部滑出确认面板（`<t-popup placement="bottom">`）：

- **乘车日期**：`<t-date-time-picker mode="date">`，默认值 `u.today()`。
  ⚠️ **日期不参与任何查询**——GTFS 没有开行日历，每天的车次列表完全一样，
  它纯粹是这条记录的元数据。所以**不要做「这天这趟车开不开」的校验**，
  也不要因为日期在未来/很久以前就拦住用户（补录三年前的行程是明确支持的场景）。
- **备注**：`<t-textarea maxlength="200" placeholder="可选，比如同行的人、座位号">`。
- 「保存」按钮 → `api.rail.createJourney({ train_number, ride_date, from_seq, to_seq, note, source: 'timetable' })`。
  成功后 `wx.showToast({title:'已记录'})` → `wx.navigateBack()`。
  行程页的 `onShow` 会自动刷新，**不需要事件总线或全局变量**。

`train_number` 传**后端返回的完整车次号**（`timetable()` 响应里的 `number`），
不是用户输入的那段别名。

### 第 4 步（可选分支）：手填模式

搜不到车次时的兜底。表单：车次号（自由输入）、乘车日期、上车站名、下车站名、备注。
提交 `source: 'manual'`，`from_seq`/`to_seq` 不传。

⚠️ 手填记录**不编造时刻也不编造里程**（spec 明确决策）。所以手填表单里
**不要有时刻输入框**，也不要提示用户「里程将自动计算」——它不会。
后端对手填记录要求 `from_station` 和 `to_station` 都非空，否则 422。

## 错误处理

`api.js` 的 `request` 已经把后端 `detail` 透传成 `Error.message`，且都是现成中文文案
（「没有找到车次 G999。」「下车站必须在上车站之后。」「铁路时刻表尚未同步，请稍后重试。」）。
一律 `wx.showToast({ title: e.message, icon: 'none' })` 直接展示，**不要自己再包一层文案**。

401 由 `api.js` 自动重登重试，不用管。

## 需要在 `rail-entry.json` 里声明的组件

至少 `t-search / t-empty / t-popup / t-date-time-picker / t-textarea / t-loading`。
`t-icon / t-button / t-cell / t-tag` 已全局注册。

## 验收

- 搜 `G1` → 能选中 → 停站表展开 7 站 → 点北京南、点上海虹桥 →
  摘要显示 `7 站 · 1318 km` → 存下来在行程页能看到。
- 搜 `K554` → 结果里是 `K551/K554`，能正常选中并展开。
- 选一个跨日车次（如 `K315/K318`），确认后段站点显示了 `+1天` 标注。
- 先点第 5 站再点第 2 站 → 重置为以第 2 站为上车站，不报错。
- 手填一条 1990 年的记录 → 能存下，行程页显示「手填」标签、时刻与里程是破折号。
- 时刻表尚未同步时（后端 503）→ 显示后端那句中文提示，不白屏。

## Comments

实现于 `miniprogram/pages/rail-entry/` 四个文件，未动任何共享文件。

### 与 issue 描述的偏离

1. **`t-date-time-picker` 必须显式传 `start`**。TDesign 的默认可选范围是
   `dayjs().subtract(10, 'year')` ~ `dayjs().add(10, 'year')`（见
   `miniprogram_npm/tdesign-miniprogram/date-time-picker/date-time-picker.js`
   的 `getMinDate`/`getMaxDate`），不设 `start` 的话「补录 1990 年」这条验收直接做不到。
   故传 `start="1950-01-01"`；`end` 保持默认（+10 年），未来日期不拦。
2. **「重选」按钮常驻但会置灰**。issue 要求「提示条上永远有一个重选按钮」，
   照做了；但一个没得可重选时仍可点的按钮是坏交互，所以未选站时给它
   `opacity: .3` 且 `onReset` 直接 return。位置常驻，提示条高度不会跳动。
3. **搜索步骤多了一个常驻的手填入口**。issue 只要求「无结果时」给手填按钮，
   但那样用户不先搜一次就进不了手填模式。初始空态底部加了一行
   「找不到车次？用手填模式记录」。无结果态的按钮照 issue 保留。
4. **手填表单的车次号不做大写转换**（后端 `create_journey` 已 `.strip().upper()`），
   前端不重复处理，避免用户输入中途被跳字。

### 自行拍板的交互细节

- **区段已选完后再点任一站** → 按「开新一轮」处理，该站成为新的上车站。
  issue 只规定了「第二次点」的三种情况，没说第三次。重新开始比报错或忽略都合理。
- **确认面板被关掉后**，点提示条可以重新叫出来；否则区段选好了却没有入口，
  只能「重选」再点一遍两个站。
- **搜索中不清空已有结果**：`wx:if="{{searching && !results.length}}"`，
  只在首次无结果时才显示 loading，避免每敲一个字整块闪。
- **乱序返回保护**：`_reqSeq` 自增，只接受最后一次请求的结果。防抖 300ms 之外，
  慢网下先发的请求后到会把结果冲掉。
- **停站点选只做增量 `setData`**：`patch['stops[i].mark']`，只推 mark 变了的行。
  上百站的普速车整表 setData 会明显卡顿。
- **区段染色**：上车/下车站圆点变品牌色带辉光，中间站整行浅蓝底，区段内竖线整段染色；
  上车站的上半段线与下车站的下半段线保持灰色（它们在区段之外）。
- **始发/终到站圆点**为空心描边大圆点，与途中站的小实心点区分（issue 要求「加粗/变色」）。
- 保存成功后 `wx.showToast` 再 `setTimeout(600)` 才 `navigateBack`，
  立刻返回的话 toast 会看不见。
- 页面标题 `记录乘车`（`rail-entry.json` 的 `navigationBarTitleText`）。

### 需要在开发者工具/真机验证的点

1. **`position: sticky` 的提示条**。停站表用的是页面级滚动 + 提示条 `position: sticky; top: 0`。
   小程序 WebView 渲染层支持 sticky，但若目标基础库版本偏低或开了 Skyline，
   可能需要改成 `position: fixed` + 列表 `padding-top`。
2. **弹层叠放**。确认面板（`t-popup`，z-index 11500）打开时再拉起
   `t-date-time-picker`（内部也是 popup，同样 11500）。日期选择器在 WXML 中写在
   确认面板之后，理论上后写的盖上面，但同 z-index 的叠放要眼见为实。
3. **超长停站表的滚动流畅度**。没做虚拟列表也没做 `scroll-view`，
   `stop_count` 上百的普速车（K/T 字头）需要实测滑动是否跟手。
4. **`t-textarea` 在 `t-popup` 里的键盘顶起行为**。用了默认 `adjust-position`，
   底部弹层 + 输入法的组合在真机上容易遮挡，需看一眼。
5. **跨日标注的实际观感**。`+1天` 用橙色小字跟在发车时刻后面，
   `K315/K318` 这类后段全是 `+1天` 的车次，一列橙字会不会太吵。
6. **`t-search` 的 `bind:change` 触发频率**。中文输入法组合态下微信的
   `bindinput` 行为在工具和真机上不完全一致，车次号是纯 ASCII 应该无碍，
   但防抖窗口是否够仍需实测。
7. 后端 503（时刻表未同步）路径只按代码推演，没有真实触发过。
